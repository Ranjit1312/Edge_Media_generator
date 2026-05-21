"""
ONNX Export Script — One-Time Cross-Encoder Conversion
======================================================
Converts the PyTorch-based ms-marco-MiniLM-L-6-v2 cross-encoder into a
quantized ONNX binary (~30MB) for air-gapped, zero-CUDA deployment.

This script requires torch and sentence-transformers installed. It is meant
to run ONCE on a development machine, not on the production edge device.

Usage:
    pip install sentence-transformers torch onnx onnxruntime
    python scripts/export_onnx.py

Output:
    models/cross-encoder/model.onnx      (~30MB quantized INT8)
    models/cross-encoder/tokenizer.json  (HuggingFace fast tokenizer)
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "models", "cross-encoder")
MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def main():
    print("=" * 60)
    print("  ONNX Cross-Encoder Export")
    print("=" * 60)
    print(f"  Source model: {MODEL_NAME}")
    print(f"  Output dir:   {OUTPUT_DIR}")
    print()

    # Check if already exported
    onnx_path = os.path.join(OUTPUT_DIR, "model.onnx")
    tokenizer_path = os.path.join(OUTPUT_DIR, "tokenizer.json")
    if os.path.exists(onnx_path) and os.path.exists(tokenizer_path):
        size_mb = os.path.getsize(onnx_path) / (1024 * 1024)
        print(f"[SUCCESS] ONNX model already exists ({size_mb:.1f}MB). Skipping export.")
        return

    # Import heavy deps (only needed during export)
    try:
        import torch
        import numpy as np
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
    except ImportError as e:
        print(f"[ERROR] Missing dependency: {e}")
        print("    Run: pip install sentence-transformers torch onnx")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Load the model and tokenizer
    print("[1/4] Loading PyTorch model from HuggingFace...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
    model.eval()

    # 2. Save the tokenizer for runtime use
    print("[2/4] Saving tokenizer...")
    tokenizer.save_pretrained(OUTPUT_DIR)
    print(f"      Saved to: {tokenizer_path}")

    # 3. Export to ONNX
    print("[3/4] Exporting to ONNX format...")
    dummy_input = tokenizer(
        "What is AI?", "Artificial intelligence is a field of computer science.",
        return_tensors="pt", max_length=512, truncation=True, padding="max_length"
    )

    onnx_raw_path = os.path.join(OUTPUT_DIR, "model_fp32.onnx")

    torch.onnx.export(
        model,
        (dummy_input["input_ids"], dummy_input["attention_mask"]),
        onnx_raw_path,
        input_names=["input_ids", "attention_mask"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq_len"},
            "attention_mask": {0: "batch", 1: "seq_len"},
        },
        opset_version=14,
        do_constant_folding=True,
    )
    raw_size = os.path.getsize(onnx_raw_path) / (1024 * 1024)
    print(f"      FP32 model exported ({raw_size:.1f}MB)")

    # 4. Quantize to INT8
    print("[4/4] Quantizing to INT8...")
    try:
        from onnxruntime.quantization import quantize_dynamic, QuantType
        quantize_dynamic(
            onnx_raw_path,
            onnx_path,
            weight_type=QuantType.QUInt8,
        )
        quant_size = os.path.getsize(onnx_path) / (1024 * 1024)
        print(f"      Quantized model saved ({quant_size:.1f}MB)")
        # Clean up FP32 model
        os.remove(onnx_raw_path)
    except ImportError:
        # If quantization tools not available, use FP32
        print("      onnxruntime quantization not available. Using FP32 model.")
        os.rename(onnx_raw_path, onnx_path)
        quant_size = raw_size

    print()
    print(f"[SUCCESS] Export complete!")
    print(f"    ONNX model:  {onnx_path} ({quant_size:.1f}MB)")
    print(f"    Tokenizer:   {tokenizer_path}")
    print()
    print("    The production system will load these files via onnxruntime.")
    print("    No torch/CUDA imports needed at runtime.")


if __name__ == "__main__":
    main()
