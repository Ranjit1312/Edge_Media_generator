"""
Cross-Encoder ONNX Model Bundler — One-Time Setup Script
========================================================
Ensures the ms-marco-MiniLM-L-6-v2 ONNX quantized model and tokenizer.json
are bundled locally in ./models/cross-encoder/ for air-gapped CPU inference.

It will:
  1. Try running export_onnx.py locally if torch & sentence_transformers are available.
  2. Fall back to downloading the pre-quantized ONNX model and tokenizer directly
     from Xenova's HuggingFace repository (Transformers.js official port).
"""
import os
import sys
import urllib.request

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(PROJECT_ROOT, "models", "cross-encoder")
ONNX_PATH = os.path.join(MODEL_DIR, "model.onnx")
TOKENIZER_PATH = os.path.join(MODEL_DIR, "tokenizer.json")

def download_file(url, dest):
    print(f"[DOWNLOAD] Downloading {url} ...")
    try:
        def report_progress(block_num, block_size, total_size):
            read_so_far = block_num * block_size
            if total_size > 0:
                percent = min(100, (read_so_far * 100) // total_size)
                sys.stdout.write(f"\r    {percent}% completed")
                sys.stdout.flush()
            else:
                sys.stdout.write(".")
                sys.stdout.flush()

        urllib.request.urlretrieve(url, dest, reporthook=report_progress)
        print("\n    [OK] Download complete.", flush=True)
        return True
    except Exception as e:
        print(f"\n    [ERROR] Failed to download: {e}", flush=True)
        return False

def main():
    print("=" * 60)
    print("  ONNX Cross-Encoder Model Bundler")
    print("=" * 60)
    print(f"  Target directory: {MODEL_DIR}")
    print()

    # Create directory
    os.makedirs(MODEL_DIR, exist_ok=True)

    if os.path.exists(ONNX_PATH) and os.path.exists(TOKENIZER_PATH):
        onnx_size = os.path.getsize(ONNX_PATH) / (1024 * 1024)
        print(f"[SUCCESS] ONNX model already bundled ({onnx_size:.1f}MB). Skipping setup.")
        return

    # Attempt 1: Local PyTorch-to-ONNX Export
    try:
        import torch
        import sentence_transformers
        print("[*] Found torch and sentence_transformers. Running export_onnx.py...")
        sys.path.append(os.path.join(PROJECT_ROOT, "scripts"))
        from export_onnx import main as run_export
        run_export()
        if os.path.exists(ONNX_PATH) and os.path.exists(TOKENIZER_PATH):
            print("[SUCCESS] Successfully exported ONNX model locally.")
            return
    except Exception as e:
        print(f"[*] Local PyTorch export not possible or failed: {e}")
        print("[*] Falling back to direct HuggingFace download...")

    # Attempt 2: Direct Download from HuggingFace
    hf_model_url = "https://huggingface.co/Xenova/ms-marco-MiniLM-L-6-v2/resolve/main/onnx/model_quantized.onnx"
    hf_tokenizer_url = "https://huggingface.co/Xenova/ms-marco-MiniLM-L-6-v2/resolve/main/tokenizer.json"

    print(f"[DOWNLOAD] Fetching pre-quantized ONNX model from HuggingFace...")
    model_success = download_file(hf_model_url, ONNX_PATH)
    tokenizer_success = download_file(hf_tokenizer_url, TOKENIZER_PATH)

    if model_success and tokenizer_success:
        print()
        print(f"[SUCCESS] ONNX model successfully bundled to: {MODEL_DIR}")
        print("    Air-gapped CPU-only RAG pipeline is fully ready.")
    else:
        print()
        print("[ERROR] Failed to bundle cross-encoder files.")
        print("    The system will fall back to keyword scoring if these files are missing.")
        sys.exit(1)

if __name__ == "__main__":
    main()
