"""
Rotating JSONL Pipeline Event Logger — Production Plane
=======================================================
Thread-safe structured event logging to rotating daily JSONL files.
Used in all deployments (air-gapped production) to capture hardware init
events, node timings, API timeouts, validation errors, and fallback triggers.

Log files are stored in ./logs/ and rotated daily, retaining 7 days.
"""
from __future__ import annotations

import os
import json
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# ─── Configuration ────────────────────────────────────────────────────────────
_LOG_DIR = Path(__file__).parent.parent / "logs"
_MAX_DAYS = 7

# ─── Thread-safe singleton ────────────────────────────────────────────────────
_logger_lock = threading.Lock()
_current_date: Optional[str] = None
_current_file = None


def _get_log_file():
    """Returns the current log file handle, rotating if the date has changed."""
    global _current_date, _current_file

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if _current_date == today and _current_file is not None:
        return _current_file

    # Date changed — close old file and open new one
    if _current_file is not None:
        try:
            _current_file.close()
        except Exception:
            pass

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _LOG_DIR / f"pipeline-{today}.jsonl"
    _current_file = open(log_path, "a", encoding="utf-8", buffering=1)
    _current_date = today

    # Purge old log files beyond retention window
    _purge_old_logs()

    return _current_file


def _purge_old_logs():
    """Removes JSONL log files older than _MAX_DAYS days."""
    try:
        cutoff = time.time() - (_MAX_DAYS * 86400)
        for f in _LOG_DIR.glob("pipeline-*.jsonl"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except Exception:
        pass


# ─── Public API ───────────────────────────────────────────────────────────────

EVENT_TYPES = (
    "hardware_init",
    "node_start",
    "node_complete",
    "node_failed",
    "fallback_triggered",
    "validation_error",
    "api_timeout",
    "cross_encoder_result",
    "pipeline_start",
    "pipeline_complete",
    "pipeline_failed",
    "loopback_triggered",
    "config_written",
)


def log_event(
    node: str,
    event_type: str,
    message: str,
    metadata: Optional[Dict[str, Any]] = None,
):
    """
    Writes a structured JSONL event to the rotating log file.

    Args:
        node:        The agent node or system component name (e.g. 'researcher', 'system').
        event_type:  One of the EVENT_TYPES constants.
        message:     Human-readable description of the event.
        metadata:    Optional dict of additional structured data.
    """
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "node": node,
        "event": event_type,
        "msg": message,
    }
    if metadata:
        record["meta"] = metadata

    line = json.dumps(record, default=str)

    with _logger_lock:
        try:
            f = _get_log_file()
            f.write(line + "\n")
        except Exception as write_err:
            # Never let logging crash the pipeline
            print(f"[LOGGER] Write error: {write_err}", flush=True)


def log_node_start(node: str, details: Optional[Dict[str, Any]] = None):
    log_event(node, "node_start", f"Node '{node}' started.", details)


def log_node_complete(node: str, duration_ms: float, details: Optional[Dict[str, Any]] = None):
    meta = {"duration_ms": round(duration_ms, 1)}
    if details:
        meta.update(details)
    log_event(node, "node_complete", f"Node '{node}' completed in {duration_ms:.0f}ms.", meta)


def log_node_failed(node: str, error: str):
    log_event(node, "node_failed", f"Node '{node}' failed: {error}", {"error": error})


def log_fallback(node: str, reason: str):
    log_event(node, "fallback_triggered", f"Fallback triggered in '{node}': {reason}", {"reason": reason})


def log_validation_error(node: str, field: str, error: str):
    log_event(node, "validation_error", f"Validation error in '{node}' on field '{field}'.", {"field": field, "error": error})


def log_hardware_init(gpu_name: str, vram_gb: float, cuda_device: str, model: str):
    log_event(
        "system", "hardware_init",
        f"Hardware initialized: {gpu_name} ({vram_gb}GB VRAM) → CUDA:{cuda_device}, model='{model}'",
        {"gpu": gpu_name, "vram_gb": vram_gb, "cuda_device": cuda_device, "model": model}
    )


def log_cross_encoder(original: int, filtered: int, dropped: int, top_score: float):
    log_event(
        "researcher", "cross_encoder_result",
        f"Cross-encoder: {original} → {filtered} articles (dropped {dropped}, top_score={top_score:.3f})",
        {"original": original, "filtered": filtered, "dropped": dropped, "top_score": top_score}
    )
