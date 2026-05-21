"""
Non-Blocking Langfuse Telemetry Tap — Developer Plane
======================================================
Activated ONLY when DEV_MODE=true AND LANGFUSE keys are set.
In production (DEV_MODE=false), this module is a complete no-op — Langfuse
is never even imported, ensuring zero CPU/memory overhead.

When active, routes telemetry to self-hosted Langfuse at localhost:3000
(or LANGFUSE_HOST override) for per-model A/B comparison.
"""
from __future__ import annotations

import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

# ─── State ───────────────────────────────────────────────────────────────────
_enabled: bool = False
_client = None
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="langfuse-tap")
_init_lock = threading.Lock()
_trace_id: Optional[str] = None

# Thread-safe in-memory running dictionary of execution metrics
_current_run: Dict[str, Any] = {}
_current_run_lock = threading.Lock()


def _initialize():
    """Attempts to initialize the Langfuse client. Gated by DEV_MODE env var."""
    global _enabled, _client

    # GATE 1: DEV_MODE must be explicitly true
    dev_mode = os.environ.get("DEV_MODE", "false").lower() in ("true", "1", "yes")
    if not dev_mode:
        print("[TELEMETRY] DEV_MODE is off — telemetry tap disabled (zero overhead).", flush=True)
        _enabled = False
        return

    # GATE 2: Langfuse keys must be set
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
    # Default to self-hosted Langfuse on localhost:3000
    host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")

    if not public_key or not secret_key:
        print(
            "[TELEMETRY] DEV_MODE=true but Langfuse keys not set — telemetry disabled. "
            "Set LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY to enable.",
            flush=True
        )
        _enabled = False
        return

    try:
        from langfuse import Langfuse
        _client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        _enabled = True
        print(f"[TELEMETRY] Langfuse tap active → host={host}", flush=True)
    except ImportError:
        print("[TELEMETRY] langfuse package not installed — tap disabled.", flush=True)
        _enabled = False
    except Exception as e:
        print(f"[TELEMETRY] Langfuse init failed ({e}) — tap disabled.", flush=True)
        _enabled = False


def initialize():
    """Public initializer — called once at application startup."""
    with _init_lock:
        _initialize()


def is_enabled() -> bool:
    return _enabled


# ─── Trace Management ─────────────────────────────────────────────────────────

def start_trace(subject: str, model: str) -> Optional[str]:
    """
    Starts a Langfuse trace for a pipeline run.
    Returns the trace_id, or None if telemetry is disabled.
    """
    global _trace_id

    # ALWAYS update thread-safe in-memory telemetry
    with _current_run_lock:
        _current_run.clear()
        
        # Load current active per-node model assignments dynamically
        node_assignments = {}
        try:
            from app.model_registry import get_fleet_status
            fleet = get_fleet_status()
            node_assignments = fleet.get("node_assignments", {})
        except Exception as e:
            print(f"[TELEMETRY] Error fetching fleet status for trace: {e}", flush=True)

        _current_run.update({
            "subject": subject,
            "model_name": model,
            "start_time": time.time(),
            "end_time": None,
            "node_assignments": node_assignments,
            "nodes": {},
            "model_swaps": [],
            "cross_encoder_stats": [],
            "node_events": [],
            "status": "running"
        })

    if not _enabled or _client is None:
        return None

    def _start():
        global _trace_id
        try:
            trace = _client.trace(
                name="animation-pipeline",
                input={"subject": subject},
                metadata={"model": model}
            )
            _trace_id = trace.id
        except Exception as e:
            print(f"[TELEMETRY] start_trace failed: {e}", flush=True)

    _executor.submit(_start)
    return _trace_id


def end_trace(output_summary: Dict[str, Any]):
    """Closes the active trace with a summary output."""
    # ALWAYS update thread-safe in-memory telemetry
    with _current_run_lock:
        _current_run["end_time"] = time.time()
        _current_run["status"] = "complete"
        _current_run["output_summary"] = output_summary

    if not _enabled or _client is None or _trace_id is None:
        return

    def _end():
        try:
            _client.trace(id=_trace_id, output=output_summary)
            _client.flush()
        except Exception as e:
            print(f"[TELEMETRY] end_trace failed: {e}", flush=True)

    _executor.submit(_end)


# ─── Span / Generation Events ────────────────────────────────────────────────

def log_generation(
    node: str,
    prompt_tokens: int,
    completion_tokens: int,
    duration_ms: float,
    model_name: Optional[str] = None,
    ttft_ms: Optional[float] = None,
    tokens_per_sec: Optional[float] = None,
    fallback_used: bool = False,
    validation_retries: int = 0,
):
    """
    Logs a single LLM generation event as a Langfuse span.
    Includes model_name for per-model A/B comparison in developer mode.
    """
    # ALWAYS update thread-safe in-memory telemetry
    with _current_run_lock:
        if "nodes" not in _current_run:
            _current_run["nodes"] = {}
        if node not in _current_run["nodes"]:
            _current_run["nodes"][node] = []
        
        _current_run["nodes"][node].append({
            "timestamp": time.time(),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "duration_ms": round(duration_ms, 1),
            "model_name": model_name,
            "ttft_ms": round(ttft_ms, 1) if ttft_ms is not None else None,
            "tokens_per_sec": round(tokens_per_sec, 2) if tokens_per_sec is not None else None,
            "fallback_used": fallback_used,
            "validation_retries": validation_retries,
        })

    if not _enabled or _client is None:
        return

    metadata = {
        "node": node,
        "duration_ms": round(duration_ms, 1),
        "fallback_used": fallback_used,
        "validation_retries": validation_retries,
    }
    if model_name:
        metadata["model_name"] = model_name
    if ttft_ms is not None:
        metadata["ttft_ms"] = round(ttft_ms, 1)
    if tokens_per_sec is not None:
        metadata["tokens_per_sec"] = round(tokens_per_sec, 2)

    def _log():
        try:
            _client.generation(
                trace_id=_trace_id,
                name=f"node_{node}",
                model=model_name,
                usage={
                    "input": prompt_tokens,
                    "output": completion_tokens,
                    "unit": "TOKENS"
                },
                metadata=metadata,
            )
        except Exception as e:
            print(f"[TELEMETRY] log_generation failed: {e}", flush=True)

    _executor.submit(_log)


def log_model_swap(from_model: str, to_model: str, swap_duration_ms: float):
    """Logs a model swap event with latency for A/B analysis."""
    # ALWAYS update thread-safe in-memory telemetry
    with _current_run_lock:
        if "model_swaps" not in _current_run:
            _current_run["model_swaps"] = []
        _current_run["model_swaps"].append({
            "timestamp": time.time(),
            "from_model": from_model,
            "to_model": to_model,
            "swap_duration_ms": round(swap_duration_ms, 1),
        })

    if not _enabled or _client is None:
        return

    def _log():
        try:
            _client.event(
                trace_id=_trace_id,
                name="model_swap",
                metadata={
                    "from_model": from_model,
                    "to_model": to_model,
                    "swap_duration_ms": round(swap_duration_ms, 1),
                }
            )
        except Exception as e:
            print(f"[TELEMETRY] log_model_swap failed: {e}", flush=True)

    _executor.submit(_log)


def log_cross_encoder_stats(original: int, filtered: int, duration_ms: float):
    """Logs cross-encoder performance stats as a Langfuse event."""
    # ALWAYS update thread-safe in-memory telemetry
    with _current_run_lock:
        if "cross_encoder_stats" not in _current_run:
            _current_run["cross_encoder_stats"] = []
        _current_run["cross_encoder_stats"].append({
            "timestamp": time.time(),
            "articles_in": original,
            "articles_out": filtered,
            "dropped": original - filtered,
            "duration_ms": round(duration_ms, 1),
        })

    if not _enabled or _client is None:
        return

    def _log():
        try:
            _client.event(
                trace_id=_trace_id,
                name="cross_encoder",
                metadata={
                    "articles_in": original,
                    "articles_out": filtered,
                    "dropped": original - filtered,
                    "duration_ms": round(duration_ms, 1),
                }
            )
        except Exception as e:
            print(f"[TELEMETRY] log_cross_encoder_stats failed: {e}", flush=True)

    _executor.submit(_log)


def log_node_event(node: str, event: str, metadata: Optional[Dict[str, Any]] = None):
    """Generic node event logger."""
    # ALWAYS update thread-safe in-memory telemetry
    with _current_run_lock:
        if "node_events" not in _current_run:
            _current_run["node_events"] = []
        _current_run["node_events"].append({
            "timestamp": time.time(),
            "node": node,
            "event": event,
            "metadata": metadata or {}
        })

    if not _enabled or _client is None:
        return

    def _log():
        try:
            _client.event(
                trace_id=_trace_id,
                name=f"{node}_{event}",
                metadata=metadata or {}
            )
        except Exception as e:
            print(f"[TELEMETRY] log_node_event failed: {e}", flush=True)

    _executor.submit(_log)


def get_telemetry_data() -> Dict[str, Any]:
    """Returns a deep copy of the thread-safe in-memory execution telemetry."""
    with _current_run_lock:
        import copy
        return copy.deepcopy(_current_run)
