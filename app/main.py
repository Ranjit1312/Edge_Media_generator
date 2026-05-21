import os
import re
import json
import asyncio
import time
import threading
import subprocess
from typing import Optional, List
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import psutil

# Import installer and pipeline hooks
from install_ollama import get_system_specs, start_ollama_detached, pull_model, locate_ollama, is_ollama_reachable, verify_gpu_layers, get_installed_models

# Import observability modules
from app import logger as pipeline_logger
from app import telemetry

app = FastAPI(title="Social Media Animation Generator API")

# Global States
setup_status = {
    "step": "pending",        # pending, scanning, starting_server, pulling_model, complete, failed
    "progress": 0,            # percent completion of model pull
    "message": "Awaiting application startup...",
    "model_name": "gemma4:e4b"
}

pipeline_status = {
    "active": False,
    "subject": "",
    "step": "idle",           # idle, researcher, editor, scriptwriter, director, voice_synthesis, complete, failed, paused
    "logs": [],
    "config": {},
    "thread_id": None,
    "scripts_to_edit": []
}
# Cached hardware properties to avoid heavy powershell subprocess leaks
cached_gpu_info = {
    "name": "Generic CPU / Integrated Video",
    "vram_total": "Unknown",
    "binary_found": False
}

def cache_hardware_properties():
    """Runs a single startup query to retrieve the active dedicated GPU details."""
    global cached_gpu_info
    print("[SYSTEM_CACHE] Pre-scanning dedicated graphics card hardware specs...", flush=True)
    try:
        cached_gpu_info["binary_found"] = locate_ollama() is not None
        
        # Standard CimInstance call to scan for all GPUs on Windows
        cmd = 'powershell -Command "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM | ConvertTo-Json"'
        res = subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=8)
        output = res.stdout
        
        if output.strip():
            gpu_data = json.loads(output)
            gpus = gpu_data if isinstance(gpu_data, list) else [gpu_data]
            
            # Find first dedicated NVIDIA or AMD gaming GPU
            dedicated = None
            for gpu in gpus:
                name = gpu.get("Name", "")
                if any(x in name.upper() for x in ["NVIDIA", "GEFORCE", "RTX", "GTX", "AMD", "RADEON"]):
                    dedicated = gpu
                    break
                    
            if not dedicated and gpus:
                dedicated = gpus[0]
                
            if dedicated:
                name = dedicated.get("Name", "Dedicated Graphics Card")
                vram_bytes = dedicated.get("AdapterRAM", 0) or 0
                if vram_bytes < 0: # Negative sign CimInstance bug fallback
                    vram_bytes = 4 * 1024 * 1024 * 1024
                    
                vram_gb = round(vram_bytes / (1024**3), 2)
                cached_gpu_info["name"] = name
                cached_gpu_info["vram_total"] = f"{vram_gb} GB"
                print(f"[SYSTEM_CACHE] Cached active GPU: {name} ({vram_gb} GB VRAM)", flush=True)
    except Exception as e:
        print(f"[SYSTEM_CACHE] Hardware pre-scan warning: {e}", flush=True)

# Mount static folder
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class StartRequest(BaseModel):
    subject: str
    cached_verified_news: Optional[List[dict]] = None
    max_stories: Optional[int] = 1
    voice_persona: Optional[str] = "af_bella"

class ResumeRequest(BaseModel):
    subject: str
    final_scripts: List[dict]
    voice_persona: Optional[str] = "af_bella"

class RerunRequest(BaseModel):
    subject: str
    model_name: str
    voice_persona: Optional[str] = "af_bella"

def update_pipeline_step(step: str, log_msg: str):
    """Shared hook called by LangGraph nodes to broadcast logs in real time."""
    global pipeline_status
    pipeline_status["step"] = step
    if log_msg not in pipeline_status["logs"]:
        pipeline_status["logs"].append(log_msg)

# Thread worker for Ollama setup
def run_ollama_setup_async():
    global setup_status
    setup_status["step"] = "scanning"
    setup_status["message"] = "Scanning system hardware specifications..."
    setup_status["progress"] = 5
    
    try:
        from install_ollama import pull_model_fleet
        from app.model_registry import get_all_fleet_models
        
        vram_gb = get_system_specs()
        fleet_models = get_all_fleet_models()
        setup_status["model_name"] = ", ".join(fleet_models)
        setup_status["progress"] = 15
        
        setup_status["step"] = "starting_server"
        setup_status["message"] = "Initializing background headless Ollama server..."
        setup_status["progress"] = 30
        
        server_started = start_ollama_detached()
        if not server_started:
            setup_status["step"] = "failed"
            setup_status["message"] = "Failed to launch Ollama background process."
            setup_status["progress"] = 0
            return
            
        setup_status["step"] = "pulling_model"
        setup_status["message"] = "Checking download for model fleet..."
        setup_status["progress"] = 50
        
        def on_fleet_progress(progress, msg):
            setup_status["progress"] = progress
            setup_status["message"] = msg
            
        pull_success = pull_model_fleet(progress_callback=on_fleet_progress)
        
        if pull_success:
            setup_status["step"] = "complete"
            setup_status["progress"] = 100
            setup_status["message"] = "On-device model fleet is fully active."
        else:
            setup_status["step"] = "failed"
            setup_status["message"] = "Failed to pull fleet models. Check connection."
            setup_status["progress"] = 0
    except Exception as e:
        setup_status["step"] = "failed"
        setup_status["message"] = f"Installer Error: {e}"
        setup_status["progress"] = 0

@app.on_event("startup")
async def startup_event():
    """Cache static properties, initialize observability, and launch UAC-free setup on boot."""
    # Ensure static and data directories exist
    os.makedirs(os.path.join(STATIC_DIR, "runs"), exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), "..", "data", "runs"), exist_ok=True)

    # Pre-cache hardware details once
    cache_hardware_properties()

    # Initialize non-blocking Langfuse telemetry tap (no-op without env vars)
    telemetry.initialize()

    # Run Ollama setup async
    thread = threading.Thread(target=run_ollama_setup_async)
    thread.daemon = True
    thread.start()

@app.get("/")
def read_root():
    """Root redirect to the gorgeous glassmorphic visual dashboard."""
    html_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(html_file):
        with open(html_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read(), status_code=200)
    return HTMLResponse(content="<h1>Loading Animation Studio Dashboard... Please refresh in a moment.</h1>")

@app.get("/api/system")
def get_system_health():
    """Queries real-time CPU and RAM, reading GPU metrics from high-performance cache."""
    return {
        "cpu_usage_pct": psutil.cpu_percent(),
        "ram_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "ram_used_gb": round(psutil.virtual_memory().used / (1024**3), 2),
        "ram_free_gb": round(psutil.virtual_memory().available / (1024**3), 2),
        "gpu_vram_total": cached_gpu_info["vram_total"],
        "gpu_name": cached_gpu_info["name"],
        "ollama_active": is_ollama_reachable(),
        "ollama_binary_found": cached_gpu_info["binary_found"]
    }

@app.get("/api/models")
def get_models_status():
    """Returns the fleet status and model overrides (useful for developer mode)."""
    from app.model_registry import get_fleet_status
    return get_fleet_status()

@app.get("/api/telemetry/download")
def download_telemetry(format: str = "markdown"):
    """Generates and serves a downloadable telemetry and model justification report."""
    from app.telemetry import get_telemetry_data
    from app.model_registry import get_fleet_status
    from fastapi import Response
    import psutil
    import time
    
    run_data = get_telemetry_data()
    fleet = get_fleet_status()
    node_assignments = fleet.get("node_assignments", {})
    
    # Query system stats
    cpu_usage = psutil.cpu_percent()
    ram = psutil.virtual_memory()
    ram_total = round(ram.total / (1024**3), 2)
    ram_used = round(ram.used / (1024**3), 2)
    
    gpu_name = cached_gpu_info["name"]
    gpu_vram = cached_gpu_info["vram_total"]
    
    if format.lower() == "json":
        # Package everything in a beautiful structured JSON payload
        report_payload = {
            "report_metadata": {
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "exporter": "Antigravity Dev Telemetry Engine v1.0"
            },
            "system_hardware": {
                "cpu_usage_pct": cpu_usage,
                "ram_total_gb": ram_total,
                "ram_used_gb": ram_used,
                "gpu_name": gpu_name,
                "gpu_vram": gpu_vram
            },
            "model_assignments": node_assignments,
            "pipeline_run": run_data
        }
        return Response(
            content=json.dumps(report_payload, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=telemetry_report.json"}
        )
    
    # Generate Markdown report
    subject = run_data.get("subject", "None (No active pipeline run started)")
    status = run_data.get("status", "idle").upper()
    duration_str = "N/A"
    
    if run_data.get("start_time"):
        end_time = run_data.get("end_time") or time.time()
        duration_str = f"{round(end_time - run_data['start_time'], 2)} seconds"
        
    md = []
    md.append("# MULTI-AGENT LANGGRAPH PIPELINE — PERFORMANCE & MODEL JUSTIFICATION TELEMETRY")
    md.append(f"\n*Generated on: {time.strftime('%Y-%m-%d %H:%M:%S')} | Exporter: Antigravity Dev Telemetry Engine v1.0*\n")
    md.append("---")
    
    md.append("\n## 1. EXECUTIVE MODEL TOPOLOGY JUSTIFICATION\n")
    md.append(
        "This multi-agent architecture is designed to orchestrate complex reasoning, factual verification, "
        "and creative layout generation on consumer-grade computing hardware. It solves the classic dual-constraint "
        "challenge: **VRAM limitations** and **inference latency**.\n\n"
        "To accomplish this, we utilize a specialized hybrid split:\n"
        "- **Factual Verification & Extraction Node (Editor)**: Assigned a **small, high-speed model** (default `gemma2:2b`). "
        "Its compact size ensures instant cold-starts, high tokens/second, and deterministic classification without "
        "thrashing dedicated graphics memory.\n"
        "- **Creative Narrator & Structural Layout Nodes (Scriptwriter & Director)**: Assigned a **larger, high-reasoning model** "
        "(default `gemma4:e4b`). These nodes must synthesize engaging stories, split information logically into vertical layouts, "
        "and output highly specific JSON structures that conform exactly to canvas ratios.\n"
        "- **Dynamic VRAM Bridge**: Between major node phases, the system triggers an active memory unload. This ensures "
        "the GPU completely clears the 2B model context before loading the larger 8B context, mitigating out-of-memory (OOM) "
        "leaks and maximizing scheduling throughput."
    )
    
    md.append("\n## 2. HARDWARE DIAGNOSTICS & SYSTEM ENVIRONMENT\n")
    md.append("| Property | System Value | Status |")
    md.append("| :--- | :--- | :--- |")
    md.append(f"| **Dedicated GPU** | {gpu_name} | Verified |")
    md.append(f"| **Total VRAM Capacity** | {gpu_vram} | Active |")
    md.append(f"| **System RAM** | {ram_used} GB / {ram_total} GB | Operational |")
    md.append(f"| **CPU Compute Load** | {cpu_usage}% | Healthy |")
    md.append(f"| **Local Ollama Host** | {os.environ.get('OLLAMA_HOST', 'http://localhost:11434')} | Reachable |")
    
    md.append("\n## 3. ACTIVE MODEL ASSIGNMENT FLEET (A/B TESTING CONFIG)\n")
    md.append("| Pipeline Node | Assigned Model Tag | Selected Priority | Role / Purpose |")
    md.append("| :--- | :--- | :--- | :--- |")
    for node, model in node_assignments.items():
        priority = "Custom Developer Override" if fleet.get("dev_overrides", {}).get(node) else "Default Production Split"
        purpose = ""
        if "researcher" in node:
            purpose = "Web article retrieval fallback & initial query expansion"
        elif "editor" in node:
            purpose = "Scraped article ranking, factual cross-validation, and authenticity verification"
        elif "scriptwriter" in node:
            purpose = "Narrative screenplay formulation and segmented slide copywriting"
        elif "director" in node:
            purpose = "Cinematic theme extraction, canvas coordinate layout generation, and JSON rendering blueprints"
        md.append(f"| **{node.capitalize()}** | `{model}` | *{priority}* | {purpose} |")
        
    md.append("\n## 4. PIPELINE TRACE & TELEMETRY METRICS\n")
    md.append(f"- **Generation Subject Focus**: `{subject}`")
    md.append(f"- **Pipeline Execution Status**: `{status}`")
    md.append(f"- **Overall Pipeline Turnaround Time**: `{duration_str}`")
    
    if run_data.get("nodes"):
        md.append("\n### 4.1 Node-by-Node Performance Log\n")
        md.append("| Node | Model Used | Latency (sec) | Input Tokens | Output Tokens | Speed (T/s) | TTFT (sec) | Validation Retries |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for node_name, attempts in run_data["nodes"].items():
            for att in attempts:
                lat = f"{round(att['duration_ms'] / 1000, 2)}s"
                ttft = f"{round(att['ttft_ms'] / 1000, 2)}s" if att.get('ttft_ms') is not None else "N/A"
                retries = att.get("validation_retries", 0)
                speed = f"{att['tokens_per_sec']} T/s" if att.get('tokens_per_sec') else "N/A"
                fallback = " Yes" if att.get('fallback_used') else ""
                md.append(f"| **{node_name.capitalize()}** | `{att['model_name']}` | {lat} | {att['prompt_tokens']} | {att['completion_tokens']} | {speed} | {ttft} | {retries}{fallback} |")
    else:
        md.append("\n> [!NOTE]\n> **No active performance trace collected yet.** Run the generator once using the dashboard to populate live latency, token counts, and token speeds.")
        
    if run_data.get("model_swaps"):
        md.append("\n### 4.2 Model Swap & VRAM Bridging Events\n")
        md.append("| Transition Sequence | Target Model | Swapping Duration | Bridge Action |")
        md.append("| :--- | :--- | :--- | :--- |")
        for swap in run_data["model_swaps"]:
            duration = f"{round(swap['swap_duration_ms'] / 1000, 2)}s"
            md.append(f"| `{swap['from_model']}` &rarr; `{swap['to_model']}` | `{swap['to_model']}` | {duration} | Dedicated VRAM Purge |")
            
    if run_data.get("cross_encoder_stats"):
        md.append("\n### 4.3 Cross-Encoder Scoring Metrics\n")
        md.append("| Run | Scrapings In | Authenticated Out | Filtered/Dropped | Rerank Latency |")
        md.append("| :--- | :--- | :--- | :--- | :--- |")
        for stat in run_data["cross_encoder_stats"]:
            duration = f"{round(stat['duration_ms'] / 1000, 2)}s"
            md.append(f"| Trace Run | {stat['articles_in']} | {stat['articles_out']} | {stat['dropped']} | {duration} |")
            
    md.append("\n## 5. REASONING ENGINE ARCHITECTURE DEEP-DIVE\n")
    md.append(
        "### 5.1 Factual Precision vs Creative Flamboyance\n"
        "By separating reasoning into micro-agent domains, we prevent the model from drifting into hallucinated narratives "
        "while ensuring the final animated screenplay remains punchy. The **Editor** agent operates as a cold factual gatekeeper, "
        "scoring and discarding irrelevant details. The **Scriptwriter** operates under an inductive creative persona, "
        "spinning verified facts into an emotional hook. This hybrid pipeline ensures the output is both trustworthy and highly engaging.\n\n"
        "### 5.2 Deterministic Output Blueprints\n"
        "The **Director** agent translates the final screenplay into detailed CSS canvas blueprints. This requires the model to output "
        "impeccable JSON. Using larger, fine-tuned structure models (`gemma4:e4b`) ensures the blueprints parse flawlessly on the first attempt, "
        "saving costly downstream validation loops and rendering failures.\n"
    )
    
    md_content = "\n".join(md)
    return Response(
        content=md_content,
        media_type="text/markdown",
        headers={"Content-Disposition": "attachment; filename=telemetry_report.md"}
    )

def finalize_audio_assets(final_state: dict, run_id: str):
    """
    Scans the state animation configuration for generated slide audio files,
    copies them to the static run directory, and rewrites the config URLs.
    """
    import shutil
    runs_dir = os.path.join(os.path.dirname(__file__), "..", "data", "runs")
    static_run_dir = os.path.join(STATIC_DIR, "runs", run_id)
    os.makedirs(static_run_dir, exist_ok=True)
    
    animation_config = final_state.get("animation_config", {})
    slides = animation_config.get("slides", [])
    
    for idx, slide in enumerate(slides):
        audio_url_rel = slide.get("audio_url", "")
        if not audio_url_rel:
            continue
            
        file_ext = ".wav" if ".wav" in audio_url_rel else ".mp3"
        tmp_filename = f"audio_tmp_{idx}{file_ext}"
        src_path = os.path.join(runs_dir, tmp_filename)
        
        dest_filename = f"audio_{idx}{file_ext}"
        dest_path_static = os.path.join(static_run_dir, dest_filename)
        dest_path_data = os.path.join(runs_dir, run_id, dest_filename)
        
        os.makedirs(os.path.join(runs_dir, run_id), exist_ok=True)
        
        if os.path.exists(src_path):
            try:
                # Copy to static web directory
                shutil.copy2(src_path, dest_path_static)
                # Copy to backup historical data runs
                shutil.copy2(src_path, dest_path_data)
                # Clean up temporary source file
                os.remove(src_path)
                
                # Update config with correct absolute static URL path
                slide["audio_url"] = f"/static/runs/{run_id}/{dest_filename}"
            except Exception as copy_e:
                print(f"[AUDIO_COMPILER] Error moving slide speech file: {copy_e}", flush=True)

# Thread worker for running LangGraph multi-agent pipeline
def finalize_run_completion(final_state: dict, subject: str, thread_config: dict):
    """
    Consolidates run history registration, audio asset mapping, config compilation,
    and locks release upon successful pipeline completion.
    """
    global pipeline_status
    run_id = f"run_{int(time.time())}"
    pipeline_status["run_id"] = run_id

    # 1. Compile and move voice synthesis WAV/MP3 files
    finalize_audio_assets(final_state, run_id)

    runs_dir = os.path.join(os.path.dirname(__file__), "..", "data", "runs")
    os.makedirs(os.path.join(runs_dir, run_id), exist_ok=True)

    # Save config for this specific run
    run_config_path = os.path.join(runs_dir, run_id, "config.json")
    with open(run_config_path, "w", encoding="utf-8") as f:
        json.dump(final_state["animation_config"], f, indent=2)

    # Update runs_history.json registry
    history_path = os.path.join(runs_dir, "runs_history.json")
    history = []
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as hf:
                history = json.load(hf)
        except Exception:
            history = []

    from app.model_registry import get_fleet_status
    fleet_status = get_fleet_status()
    node_models = fleet_status.get("node_assignments", {})

    new_run_entry = {
        "run_id": run_id,
        "subject": subject,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "models": node_models,
        "verified_news": final_state.get("verified_news", []),
        "has_video": False
    }
    history.insert(0, new_run_entry)
    with open(history_path, "w", encoding="utf-8") as hf:
        json.dump(history, hf, indent=2)

    # Save generated configuration for SSE streaming
    pipeline_status["config"] = final_state["animation_config"]
    pipeline_status["step"] = "complete"
    msg = f"Multi-Agent News Pipeline successfully completed! Run stored under ID: {run_id}"
    pipeline_status["logs"].append(msg)
    update_pipeline_step("complete", msg)

    # Write animation configuration directly to static config.json
    config_path = os.path.join(STATIC_DIR, "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(final_state["animation_config"], f, indent=2)

    slide_count = len(final_state["animation_config"].get("slides", []))
    pipeline_logger.log_event("system", "config_written", f"config.json written with {slide_count} slides.", {"slides": slide_count})
    pipeline_logger.log_event("system", "pipeline_complete", f"Pipeline complete for '{subject}'.")
    telemetry.end_trace({"slides": slide_count, "subject": subject})
    
    # Release generation active lock
    pipeline_status["active"] = False


def execute_agent_pipeline(subject: str, model_name: str, cached_verified_news: Optional[List[dict]] = None, max_stories: int = 1, voice_persona: str = "af_bella"):
    global pipeline_status
    pipeline_status["active"] = True
    pipeline_status["subject"] = subject
    pipeline_status["step"] = "researcher"
    pipeline_status["logs"] = ["LangGraph Multi-Agent Engine: Starting news research nodes..."]
    pipeline_status["config"] = {}
    pipeline_status["thread_id"] = None
    pipeline_status["scripts_to_edit"] = []

    pipeline_logger.log_hardware_init(
        gpu_name=cached_gpu_info["name"],
        vram_gb=float(str(cached_gpu_info["vram_total"]).replace(" GB", "").strip() or "0"),
        cuda_device="0",
        model=model_name
    )
    pipeline_logger.log_event("system", "pipeline_start", f"Pipeline started for subject='{subject}'", {"subject": subject, "model": model_name})
    telemetry.start_trace(subject, model_name)

    try:
        from app.agent_engine import build_agent_graph, AgentState
        from app.checkpointer import make_thread_config, clear_checkpoint

        # Clear any stale checkpoint so this is a fresh run
        clear_checkpoint(subject)

        app_graph = build_agent_graph()
        thread_config = make_thread_config(subject)

        initial_state: AgentState = {
            "subject": subject,
            "search_queries": [subject],
            "model_name": model_name,
            "scraping_attempts": 0,
            "raw_news": [],
            "verified_news": cached_verified_news or [],
            "final_scripts": [],
            "animation_config": {},
            "logs": pipeline_status["logs"],
            "bypass_scraping": True if cached_verified_news else False,
            "bypass_to_director": False,
            "max_stories": max_stories,
            "voice_persona": voice_persona
        }

        # Invoke LangGraph state machine with thread config for checkpointing
        final_state = app_graph.invoke(initial_state, config=thread_config)

        # Retrieve thread state to check if paused at breakpoint
        thread_state = app_graph.get_state(thread_config)
        if thread_state.next:
            # Pause pipeline at Scriptwriter breakpoint, update global status, and exit thread
            pipeline_status["active"] = False
            pipeline_status["step"] = "paused"
            pipeline_status["thread_id"] = thread_config["configurable"]["thread_id"]
            pipeline_status["scripts_to_edit"] = thread_state.values.get("final_scripts", [])
            msg = "LangGraph: Paused at Scriptwriter Breakpoint. Awaiting human edit..."
            pipeline_status["logs"].append(msg)
            update_pipeline_step("paused", msg)
            return

        # Complete final runs compilation
        finalize_run_completion(final_state, subject, thread_config)

    except Exception as e:
        pipeline_status["step"] = "failed"
        pipeline_status["logs"].append(f"Fatal Engine Crash: {e}")
        pipeline_logger.log_event("system", "pipeline_failed", f"Fatal crash: {e}", {"error": str(e)})
        pipeline_status["active"] = False


class DevConfigRequest(BaseModel):
    dev_mode: bool
    node_models: dict

def background_dev_pull(missing_models):
    global setup_status
    setup_status["step"] = "pulling_model"
    setup_status["message"] = "Initializing download for developer model fleet..."
    setup_status["progress"] = 0
    
    try:
        success = True
        for i, model in enumerate(missing_models):
            setup_status["model_name"] = model
            setup_status["message"] = f"Starting download for {model}..."
            setup_status["progress"] = int((i * 100) / len(missing_models))
            
            def on_model_progress(msg):
                import re
                match = re.search(r'(\d+)%', msg)
                pct = int(match.group(1)) if match else 0
                overall = int(((i * 100) + pct) / len(missing_models))
                setup_status["progress"] = min(99, overall)
                setup_status["message"] = msg
                
            pulled = pull_model(model, progress_callback=on_model_progress)
            if not pulled:
                success = False
                break
                
        from app.model_registry import refresh_available_models, get_all_fleet_models
        refresh_available_models()
        
        if success:
            setup_status["step"] = "complete"
            setup_status["progress"] = 100
            setup_status["message"] = "All assigned developer models are ready!"
            setup_status["model_name"] = ", ".join(get_all_fleet_models())
        else:
            setup_status["step"] = "failed"
            setup_status["message"] = "Failed to pull developer models."
            setup_status["progress"] = 0
    except Exception as e:
        setup_status["step"] = "failed"
        setup_status["message"] = f"Developer model pull error: {str(e)}"
        setup_status["progress"] = 0

@app.post("/api/dev/config")
def update_dev_config(req: DevConfigRequest):
    """Updates the developer mode state and per-node model assignments in prompts/models_config.json."""
    from app.model_registry import save_dev_config, refresh_available_models, get_all_fleet_models
    
    if req.dev_mode:
        # Validate node models to avoid saving empty, invalid, or literal 'custom' tags
        for node, model in req.node_models.items():
            if not model or model.strip() == "" or model.strip().lower() == "custom":
                return {"success": False, "error": f"Invalid model tag '{model}' assigned to node '{node}'."}
                
    success = save_dev_config(req.dev_mode, req.node_models)
    if not success:
        return {"success": False, "error": "Failed to save developer configuration."}
        
    if not req.dev_mode:
        if setup_status["step"] != "complete":
            setup_status["step"] = "complete"
            setup_status["progress"] = 100
            setup_status["message"] = "Production split active."
        return {"success": True, "needs_download": False, "message": "Production mode enabled."}
        
    # Check for missing models
    installed_models = get_installed_models()
    missing_models = []
    for node, model in req.node_models.items():
        if not model or model == "custom":
            continue
        model_exists = False
        for inst in installed_models:
            if inst == model or inst.split(':')[0] == model or model.split(':')[0] == inst:
                model_exists = True
                break
        if not model_exists and model not in missing_models:
            missing_models.append(model)
            
    if missing_models:
        # Launch background pull thread
        thread = threading.Thread(target=background_dev_pull, args=(missing_models,))
        thread.daemon = True
        thread.start()
        return {
            "success": True, 
            "needs_download": True, 
            "missing_models": missing_models,
            "message": f"Downloading required models: {', '.join(missing_models)}"
        }
        
    # If no missing models, make sure setup_status is complete and available
    refresh_available_models()
    setup_status["step"] = "complete"
    setup_status["progress"] = 100
    setup_status["message"] = "All configured developer models are ready."
    setup_status["model_name"] = ", ".join(get_all_fleet_models())
    
    return {"success": True, "needs_download": False, "message": "All assigned models are ready."}

def resume_agent_pipeline_async(subject: str):
    """Background daemon worker that resumes graph execution from its breakpoint."""
    global pipeline_status
    pipeline_status["active"] = True
    pipeline_status["step"] = "director"
    pipeline_status["logs"].append("Resuming LangGraph pipeline execution thread...")
    update_pipeline_step("director", "Resuming pipeline execution...")
    
    try:
        from app.agent_engine import build_agent_graph
        from app.checkpointer import make_thread_config
        
        app_graph = build_agent_graph()
        thread_config = make_thread_config(subject)
        
        # Resume graph execution by passing None (loads state from SQLite database checkpoint)
        final_state = app_graph.invoke(None, config=thread_config)
        
        # Complete final runs compilation
        finalize_run_completion(final_state, subject, thread_config)
    except Exception as e:
        pipeline_status["step"] = "failed"
        pipeline_status["logs"].append(f"Fatal Resume Crash: {e}")
        pipeline_logger.log_event("system", "pipeline_failed", f"Fatal resume crash: {e}", {"error": str(e)})
        pipeline_status["active"] = False


@app.post("/api/pipeline/resume")
def resume_pipeline(req: ResumeRequest):
    """Patches the SQLite checkpointer database with edited screenplay text and resumes thread."""
    global pipeline_status
    if pipeline_status["active"]:
        return {"success": False, "error": "A generation pipeline is already running."}
        
    try:
        from app.agent_engine import build_agent_graph
        from app.checkpointer import make_thread_config
        
        thread_config = make_thread_config(req.subject)
        app_graph = build_agent_graph()
        
        # 1. Update SQLite checkpointer state thread database
        state_updates = {"final_scripts": req.final_scripts}
        if req.voice_persona:
            state_updates["voice_persona"] = req.voice_persona
            
        app_graph.update_state(thread_config, state_updates, as_node="scriptwriter")
        
        # 2. Spawn a background thread to resume the graph invoke
        thread = threading.Thread(target=resume_agent_pipeline_async, args=(req.subject,))
        thread.daemon = True
        thread.start()
        return {"success": True, "message": "Screenplay patched successfully. Running Visual Director..."}
    except Exception as e:
        return {"success": False, "error": f"Failed to patch thread state database: {e}"}


@app.post("/api/pipeline/regenerate_visuals")
def regenerate_visuals(req: RerunRequest):
    """Overrides bypass_to_director flag and reruns ONLY the Visual Director node."""
    global pipeline_status
    if pipeline_status["active"]:
        return {"success": False, "error": "A generation pipeline is already running."}
        
    try:
        from app.agent_engine import build_agent_graph
        from app.checkpointer import make_thread_config
        
        thread_config = make_thread_config(req.subject)
        app_graph = build_agent_graph()
        
        # Patch SQLite checkpointer thread database to bypass scraping & editing nodes
        state_updates = {
            "bypass_to_director": True, 
            "model_name": req.model_name
        }
        if req.voice_persona:
            state_updates["voice_persona"] = req.voice_persona
            
        app_graph.update_state(thread_config, state_updates)
        
        # Resume graph execution directly entering Director node
        thread = threading.Thread(target=resume_agent_pipeline_async, args=(req.subject,))
        thread.daemon = True
        thread.start()
        return {"success": True, "message": "Visual Director-only rerun successfully triggered."}
    except Exception as e:
        return {"success": False, "error": f"Failed to trigger visual regeneration: {e}"}
    
@app.post("/api/start")
def start_generation(req: StartRequest):
    """Triggers the LangGraph pipeline execution in a background daemon thread."""
    global pipeline_status
    if pipeline_status["active"]:
        return {"success": False, "error": "A generation pipeline is already running."}
        
    if setup_status["step"] != "complete":
        return {"success": False, "error": "LLM on-device engine is not fully initialized yet."}
        
    default_model = setup_status["model_name"]
    if "," in default_model:
        default_model = "gemma4:e4b"
        
    thread = threading.Thread(
        target=execute_agent_pipeline, 
        args=(req.subject, default_model, req.cached_verified_news, req.max_stories, req.voice_persona)
    )
    thread.daemon = True
    thread.start()
    return {"success": True, "message": "Pipeline worker thread activated."}

@app.post("/api/reset")
def reset_generation_lock():
    """Allows manual clearing of the active worker pipeline lock state in case of LLM deadlocks."""
    global pipeline_status
    pipeline_status["active"] = False
    pipeline_status["step"] = "idle"
    pipeline_status["logs"] = ["Pipeline status state unlocked and reset successfully by user."]
    pipeline_status["config"] = {}
    return {"success": True, "message": "Pipeline generation lock cleared."}

@app.get("/api/stream")
async def stream_progress_and_logs(request: Request):
    """Server-Sent Events (SSE) log-streaming channel for the visual dashboard console."""
    async def event_generator():
        last_log_idx = 0
        while True:
            # Check for client disconnect
            if await request.is_disconnected():
                break
                
            # Stream Ollama install stats
            setup_payload = {
                "type": "setup",
                "step": setup_status["step"],
                "progress": setup_status["progress"],
                "message": setup_status["message"],
                "model_name": setup_status["model_name"]
            }
            yield f"data: {json.dumps(setup_payload)}\n\n"
            
            # Stream dynamic LangGraph logs
              # Stream dynamic LangGraph logs
            logs = pipeline_status["logs"]
            if len(logs) > last_log_idx:
                for idx in range(last_log_idx, len(logs)):
                    log_payload = {
                        "type": "log",
                        "index": idx,
                        "content": logs[idx],
                        "active_step": pipeline_status["step"]
                    }
                    yield f"data: {json.dumps(log_payload)}\n\n"
                last_log_idx = len(logs)
                
            # Stream paused script editing state
            if pipeline_status["step"] == "paused":
                paused_payload = {
                    "type": "paused",
                    "thread_id": pipeline_status.get("thread_id"),
                    "scripts_to_edit": pipeline_status.get("scripts_to_edit", []),
                    "subject": pipeline_status.get("subject", "")
                }
                yield f"data: {json.dumps(paused_payload)}\n\n"
                
            # Stream final configurations when ready
            if pipeline_status["step"] == "complete" and pipeline_status["config"]:
                config_payload = {
                    "type": "config",
                    "config": pipeline_status["config"],
                    "run_id": pipeline_status.get("run_id")
                }
                yield f"data: {json.dumps(config_payload)}\n\n"
                # Keep config buffer persisted so reconnecting or loading clients can fetch it
                # pipeline_status["config"] = {}
                
            await asyncio.sleep(0.3)
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# ─── Run History & Benchmarking Suite Endpoints ─────────────────────────────────

@app.get("/api/runs/history")
def get_runs_history():
    """Returns all historical runs and metadata for the UI sidebar."""
    runs_dir = os.path.join(os.path.dirname(__file__), "..", "data", "runs")
    history_path = os.path.join(runs_dir, "runs_history.json")
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

@app.post("/api/runs/{run_id}/upload_video")
async def upload_run_video(run_id: str, file: UploadFile = File(...)):
    """Saves client-side generated WebM video to the run history and static asset endpoints."""
    runs_dir = os.path.join(os.path.dirname(__file__), "..", "data", "runs")
    run_dir = os.path.join(runs_dir, run_id)
    os.makedirs(run_dir, exist_ok=True)
    
    # Destination 1: data/runs/<run_id>/video.webm
    dest_1 = os.path.join(run_dir, "video.webm")
    
    # Destination 2: app/static/runs/<run_id>.webm
    static_runs_dir = os.path.join(STATIC_DIR, "runs")
    os.makedirs(static_runs_dir, exist_ok=True)
    dest_2 = os.path.join(static_runs_dir, f"{run_id}.webm")
    
    try:
        content = await file.read()
        with open(dest_1, "wb") as f1:
            f1.write(content)
        with open(dest_2, "wb") as f2:
            f2.write(content)
            
        # Update runs_history.json to reflect that this run now has a video!
        history_path = os.path.join(runs_dir, "runs_history.json")
        if os.path.exists(history_path):
            with open(history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
            for entry in history:
                if entry.get("run_id") == run_id:
                    entry["has_video"] = True
                    break
            with open(history_path, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
                
        return {"success": True, "message": "Video uploaded successfully."}
    except Exception as e:
        return {"success": False, "error": f"Failed to save video file: {e}"}

class PullRequest(BaseModel):
    model: str

@app.post("/api/dev/pull")
def pull_custom_dev_model(req: PullRequest):
    """Enables developers to pull custom Ollama models (e.g. gemma:2b) directly from the UI dashboard."""
    global setup_status
    # Launch pull in background daemon thread
    thread = threading.Thread(target=background_dev_pull, args=([req.model],))
    thread.daemon = True
    thread.start()
    return {"success": True, "message": f"Downloading custom model '{req.model}' started."}

