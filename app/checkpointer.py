"""
SQLite LangGraph State Checkpointer — Production Plane
======================================================
Wraps LangGraph's SqliteSaver to persist AgentState after every completed node.
Enables crash recovery — pipelines can resume from the last successful node
instead of restarting from scratch.

Each pipeline run is scoped to a unique thread_id derived from the subject string,
allowing concurrent runs for different subjects without state collision.

The DB file is stored at ./data/pipeline_checkpoints.db using WAL mode for
thread-safe concurrent read/write access.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

# ─── Configuration ────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).parent.parent / "data"
_DB_PATH = str(_DATA_DIR / "pipeline_checkpoints.db")

_checkpointer_instance = None


def _ensure_data_dir():
    """Creates the ./data directory if it does not exist."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_checkpointer():
    """
    Returns the module-level SqliteSaver singleton.
    Creates the database and tables on first call.
    """
    global _checkpointer_instance
    if _checkpointer_instance is not None:
        return _checkpointer_instance

    _ensure_data_dir()

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        # WAL mode for concurrent thread-safe access
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.commit()
        _checkpointer_instance = SqliteSaver(conn)
        print(f"[CHECKPOINTER] SQLite state persistence active at: {_DB_PATH}", flush=True)
    except ImportError:
        print(
            "[CHECKPOINTER] langgraph-checkpoint-sqlite not installed — "
            "state checkpointing disabled. Install with: pip install langgraph-checkpoint-sqlite",
            flush=True
        )
        _checkpointer_instance = None
    except Exception as e:
        print(f"[CHECKPOINTER] Failed to initialize SQLite checkpointer ({e}) — disabled.", flush=True)
        _checkpointer_instance = None

    return _checkpointer_instance


def make_thread_config(subject: str) -> dict:
    """
    Creates the LangGraph thread config dict for a given subject.
    The thread_id is derived from the subject to allow resume on retry.

    Usage:
        config = make_thread_config("Artificial Intelligence")
        graph.invoke(initial_state, config=config)
    """
    # Sanitize subject into a stable thread_id
    thread_id = subject.lower().strip().replace(" ", "_")[:64]
    return {"configurable": {"thread_id": thread_id}}


def clear_checkpoint(subject: str):
    """
    Clears any existing checkpoint for a subject thread.
    Called before starting a fresh run (not a resume).
    """
    try:
        if not os.path.exists(_DB_PATH):
            return
        thread_id = subject.lower().strip().replace(" ", "_")[:64]
        conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        # LangGraph SqliteSaver table is named 'checkpoints'
        conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        conn.commit()
        conn.close()
        print(f"[CHECKPOINTER] Cleared checkpoint for thread_id='{thread_id}'.", flush=True)
    except Exception as e:
        # Non-fatal — just log and continue
        print(f"[CHECKPOINTER] Could not clear checkpoint: {e}", flush=True)
