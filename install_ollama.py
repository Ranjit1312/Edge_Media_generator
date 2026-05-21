import os
import sys
import shutil
import zipfile
import urllib.request
import subprocess
import time
import json
import psutil

# Configuration
OLLAMA_ZIP_URL = "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip"
INSTALL_DIR = os.path.expandvars(r"%LOCALAPPDATA%\Ollama")
OLLAMA_EXE = os.path.join(INSTALL_DIR, "ollama.exe")
PORT = 11434
OLLAMA_URL = f"http://localhost:{PORT}"

# ─── GPU Isolation Helpers ────────────────────────────────────────────────────

def get_cuda_device_index() -> str:
    """
    Resolves the CUDA device index of the dedicated NVIDIA GPU via nvidia-smi.
    Returns '0' as the safe fallback if nvidia-smi is unavailable.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5
        )
        lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
        # Find first line containing RTX, GTX, or NVIDIA discrete GPU
        for line in lines:
            idx, name = line.split(",", 1) if "," in line else (line, "")
            name = name.strip().upper()
            if any(x in name for x in ["RTX", "GTX", "QUADRO", "TESLA", "A10", "A100"]):
                log(f"Resolved CUDA device index: {idx.strip()} -> {name}")
                return idx.strip()
        # Fallback: return first GPU index
        if lines:
            idx = lines[0].split(",")[0].strip()
            log(f"Defaulting to CUDA device index: {idx}")
            return idx
    except FileNotFoundError:
        log("nvidia-smi not found - defaulting to CUDA device 0.")
    except Exception as e:
        log(f"nvidia-smi query failed ({e}) - defaulting to CUDA device 0.")
    return "0"


def build_gpu_env() -> dict:
    """
    Builds a subprocess environment dict that locks execution to the dedicated
    NVIDIA GPU, bypassing Windows' power-saving integrated graphics scheduler.
    """
    cuda_idx = get_cuda_device_index()
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = cuda_idx
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"   # Stable GPU ordering by PCIe slot
    env["OLLAMA_GPU_OVERHEAD"] = "0"            # No VRAM overhead padding
    log(f"GPU isolation env: CUDA_VISIBLE_DEVICES={cuda_idx}, CUDA_DEVICE_ORDER=PCI_BUS_ID")
    return env


def verify_gpu_layers() -> bool:
    """
    Queries the Ollama /api/ps endpoint to verify the loaded model is using
    CUDA GPU layers (not CPU-only). Returns True if GPU layers are active.
    """
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/ps")
        with urllib.request.urlopen(req, timeout=4) as response:
            data = json.loads(response.read().decode('utf-8'))
            models = data.get("models", [])
            for m in models:
                details = m.get("details", {})
                lib = details.get("family", "") or ""
                num_gpu = m.get("size_vram", 0) or 0
                if num_gpu > 0:
                    log(f"GPU verification PASSED - model VRAM usage: {round(num_gpu / 1024**3, 2)} GB")
                    return True
            if models:
                log("WARNING: Model loaded but VRAM usage is 0. Possible CPU fallback.")
            return False
    except Exception:
        # Server not yet running or no model loaded — not an error
        return False

def log(message):
    print(f"[OllamaInstaller] {message}", flush=True)

def get_system_specs():
    """Gathers GPU VRAM and CPU/RAM specs and returns dedicated VRAM in GB."""
    log("Scanning system hardware specifications...")
    
    # Default fallback
    vram_bytes = 0
    gpu_name = "Generic CPU / Integrated Video"
    
    # Try querying GPU details via Windows PowerShell (Lightweight, no CUDA required)
    try:
        cmd = 'powershell -Command "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM | ConvertTo-Json"'
        output = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
        
        if output.strip():
            data = json.loads(output)
            # If multiple GPUs, find the dedicated one (usually NVIDIA/AMD)
            gpus = data if isinstance(data, list) else [data]
            
            # Look for NVIDIA/AMD first
            dedicated_gpu = None
            for gpu in gpus:
                name = gpu.get("Name", "")
                ram = gpu.get("AdapterRAM", 0) or 0
                if any(x in name.upper() for x in ["NVIDIA", "GEFORCE", "RTX", "GTX", "AMD", "RADEON"]):
                    dedicated_gpu = gpu
                    break
            
            if not dedicated_gpu and gpus:
                dedicated_gpu = gpus[0]
                
            if dedicated_gpu:
                gpu_name = dedicated_gpu.get("Name", "Unknown Dedicated GPU")
                vram_bytes = dedicated_gpu.get("AdapterRAM", 0) or 0
                # In some CimInstance calls, AdapterRAM might be negative or weirdly signed on Windows, handle it
                if vram_bytes < 0:
                    vram_bytes = 4 * 1024 * 1024 * 1024  # Fallback to 4GB if negative sign bug occurs
    except Exception as e:
        log(f"Warning: Could not query GPU specifications directly: {e}")

    # Read RAM specs
    ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 2)
    free_ram_gb = round(psutil.virtual_memory().available / (1024 ** 3), 2)
    vram_gb = round(vram_bytes / (1024 ** 3), 2)
    
    log(f"System Specs: CPU Cores={psutil.cpu_count()}, System RAM={ram_gb} GB ({free_ram_gb} GB Free)")
    log(f"Active Graphics Card: {gpu_name} (VRAM: {vram_gb} GB)")
    
    return vram_gb

def is_ollama_reachable():
    """Checks if the local Ollama server is already running."""
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/")
        with urllib.request.urlopen(req, timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False

def locate_ollama():
    """Finds if ollama is installed in LOCALAPPDATA or PATH."""
    if os.path.exists(OLLAMA_EXE):
        return OLLAMA_EXE
    
    path_exe = shutil.which("ollama")
    if path_exe:
        return path_exe
        
    return None

def download_and_extract_ollama():
    """Bypasses standard UAC prompts by downloading the standalone ZIP and extracting it."""
    if not os.path.exists(INSTALL_DIR):
        os.makedirs(INSTALL_DIR)
        
    zip_path = os.path.join(INSTALL_DIR, "ollama-windows-amd64.zip")
    
    log(f"Downloading standalone Ollama ZIP from {OLLAMA_ZIP_URL}...")
    
    def report_progress(block_num, block_size, total_size):
        read_so_far = block_num * block_size
        if total_size > 0:
            percent = min(100, (read_so_far * 100) // total_size)
            sys.stdout.write(f"\rDownloading: {percent}% completed")
            sys.stdout.flush()
        else:
            sys.stdout.write(".")
            sys.stdout.flush()

    try:
        urllib.request.urlretrieve(OLLAMA_ZIP_URL, zip_path, reporthook=report_progress)
        print("", flush=True)
        log("Download completed successfully! Extracting assets...")
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(INSTALL_DIR)
            
        log(f"Extraction complete! Standalone Ollama is installed at: {INSTALL_DIR}")
        
        # Cleanup zip file
        try:
            os.remove(zip_path)
        except Exception:
            pass
            
        return OLLAMA_EXE
    except Exception as e:
        log(f"ERROR: Failed to download or extract Ollama ZIP: {e}")
        raise e

def start_ollama_detached():
    """
    Launches 'ollama serve' as a completely detached background process,
    with CUDA environment variables injected to force execution on the
    dedicated NVIDIA RTX GPU instead of Windows' default integrated graphics.
    """
    if is_ollama_reachable():
        log("Ollama server is already active and listening on port 11434.")
        return True
        
    ollama_path = locate_ollama()
    if not ollama_path:
        log("Ollama binary not found. Initiating silent installation...")
        ollama_path = download_and_extract_ollama()
        
    log(f"Launching detached background Ollama server from {ollama_path}...")
    
    # Build GPU-isolation environment (forces NVIDIA RTX, bypasses Intel iGPU scheduler)
    gpu_env = build_gpu_env()
    
    # DETACHED_PROCESS | CREATE_NO_WINDOW — process survives terminal closure
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    
    try:
        subprocess.Popen(
            [ollama_path, "serve"],
            creationflags=flags,
            env=gpu_env,           # ← GPU isolation env injected here
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Poll server until it responds
        log("Waiting for Ollama background service to boot up...")
        for attempt in range(12):
            time.sleep(1.0)
            if is_ollama_reachable():
                log("Ollama server successfully activated and running!")
                return True
        log("Warning: Ollama server launched but port 11434 is not responding yet.")
        return False
    except Exception as e:
        log(f"ERROR: Failed to start detached Ollama process: {e}")
        return False

def get_installed_models():
    """Queries Ollama for currently pulled local models."""
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            return [m["name"] for m in data.get("models", [])]
    except Exception as e:
        log(f"Could not read local models: {e}")
        return []

def pull_model(model_name, progress_callback=None):
    """Pulls the specified model via the Ollama REST API, streaming progress."""
    log(f"Checking if model '{model_name}' is downloaded locally...")
    installed_models = get_installed_models()
    
    # Check both full name and base name
    model_exists = False
    for model in installed_models:
        if model == model_name or model.split(':')[0] == model_name:
            model_exists = True
            break
            
    if model_exists:
        log(f"Model '{model_name}' is already downloaded and ready to use.")
        return True
        
    log(f"Model '{model_name}' is not found locally. Initiating model pull...")
    
    url = f"{OLLAMA_URL}/api/pull"
    payload = json.dumps({"model": model_name, "stream": True}).encode('utf-8')
    
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as response:
            buffer = ""
            for chunk in iter(lambda: response.read(64), b""):
                buffer += chunk.decode('utf-8')
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        data = json.loads(line)
                        status = data.get("status", "")
                        completed = data.get("completed", 0)
                        total = data.get("total", 0)
                        
                        if total > 0:
                            percent = min(100, (completed * 100) // total)
                            progress_msg = f"Pulling {model_name}: {percent}% ({status})"
                        else:
                            progress_msg = f"Pulling {model_name}: {status}"
                            
                        if progress_callback:
                            progress_callback(progress_msg)
                        else:
                            sys.stdout.write(f"\r{progress_msg:<80}")
                            sys.stdout.flush()
            print("", flush=True)
            log(f"Model '{model_name}' successfully downloaded!")
            return True
    except Exception as e:
        log(f"\nERROR: Failed to pull model '{model_name}': {e}")
        return False

def pull_model_fleet(progress_callback=None):
    """
    Pulls the entire required model fleet sequentially.
    """
    import re
    from app.model_registry import get_all_fleet_models, refresh_available_models
    refresh_available_models()
    
    fleet = get_all_fleet_models()
    log(f"Required model fleet: {fleet}")
    
    success = True
    for i, model in enumerate(fleet):
        def model_progress_callback(msg):
            if progress_callback:
                match = re.search(r'(\d+)%', msg)
                pull_pct = int(match.group(1)) if match else 0
                
                # Compute overall fleet progress smoothly across all models
                overall_progress = 50 + int((i * 100 + pull_pct) / (len(fleet) * 2))
                progress_callback(overall_progress, f"Pulling {model}... ({pull_pct}%)")
            else:
                log(msg)
                
        if progress_callback:
            progress_callback(50 + int(i * 100 / (len(fleet) * 2)), f"Checking/Pulling {model}...")
            
        pulled = pull_model(model, progress_callback=model_progress_callback)
        if not pulled:
            success = False
            
    # Verification
    installed = get_installed_models()
    for model in fleet:
        found = False
        for inst in installed:
            if inst == model or inst.split(':')[0] == model:
                found = True
                break
        if not found:
            log(f"WARNING: Model '{model}' was not successfully verified in installed models.")
            success = False
            
    return success

def setup_on_device_llm():
    """Complete coordinator function: hardware check, install, run server, and pull model fleet."""
    try:
        vram_gb = get_system_specs()
        server_started = start_ollama_detached()
        if server_started:
            pull_success = pull_model_fleet()
            return {
                "success": pull_success,
                "vram_gb": vram_gb,
                "server_active": server_started
            }
        return {"success": False, "error": "Ollama server failed to start"}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    log("Running direct setup diagnostic...")
    result = setup_on_device_llm()
    log(f"Setup complete! Result: {result}")
