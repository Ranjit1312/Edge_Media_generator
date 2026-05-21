"""
Local Prompt Registry — JSON-Based Prompt Management
=====================================================
Loads versioned system prompts from ./prompts/prompts.json at startup.
Falls back to hardcoded defaults if the JSON file is missing or corrupt.

Usage:
    from app.prompt_registry import get_prompt
    system_prompt = get_prompt("editor")
"""
from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, Optional

# ─── Configuration ────────────────────────────────────────────────────────────
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_PROMPTS_FILE = _PROMPTS_DIR / "prompts.json"

# ─── State ─────────────────────────────────────────────────────────────────────
_prompt_cache: Dict[str, str] = {}
_loaded: bool = False

# ─── Hardcoded Defaults (used when JSON is unavailable) ────────────────────────
_DEFAULTS = {
    "researcher_fallback": (
        "You are a professional Tech Journalist. Generate realistic, detailed "
        "breaking news stories with specific companies, version numbers, and benchmarks."
    ),
    "editor": (
        "You are the Chief Editor and News Auditor. Your goal is to filter a list "
        "of raw news stories. Discard duplicates, clickbait, rumors. Write RICH summaries "
        "(3-4 sentences, 60-80 words minimum)."
    ),
    "scriptwriter": (
        "You are an Expert Social Media Scriptwriter writing highly engaging scripts "
        "for portrait mobile feeds (TikTok/Reels)."
    ),
    "director": (
        "You are the Creative Visual Director for a cinematic social media animation studio. "
        "Each slide is a UNIQUE 30-60 second story scene. Give each slide its own visual identity."
    ),
}


def _load_prompts():
    """Loads prompts from the JSON file into cache."""
    global _prompt_cache, _loaded

    if _loaded:
        return

    # Try environment variable for custom path
    custom_path = os.environ.get("PROMPT_REGISTRY_PATH")
    prompts_path = Path(custom_path) if custom_path else _PROMPTS_FILE

    try:
        if prompts_path.exists():
            with open(prompts_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            prompts = data.get("prompts", {})
            version = data.get("version", "unknown")

            for node_name, entry in prompts.items():
                if isinstance(entry, dict):
                    _prompt_cache[node_name] = entry.get("system", "")
                elif isinstance(entry, str):
                    _prompt_cache[node_name] = entry

            print(
                f"[PROMPT_REGISTRY] Loaded {len(_prompt_cache)} prompts from "
                f"{prompts_path} (v{version})",
                flush=True
            )
        else:
            print(
                f"[PROMPT_REGISTRY] Prompts file not found at {prompts_path}. "
                f"Using hardcoded defaults.",
                flush=True
            )
            _prompt_cache = dict(_DEFAULTS)

    except (json.JSONDecodeError, KeyError, Exception) as e:
        print(
            f"[PROMPT_REGISTRY] Failed to load prompts ({e}). Using hardcoded defaults.",
            flush=True
        )
        _prompt_cache = dict(_DEFAULTS)

    _loaded = True


def get_prompt(node_name: str) -> str:
    """
    Returns the system prompt for a given node.

    Args:
        node_name: One of 'researcher_fallback', 'editor', 'scriptwriter', 'director'

    Returns:
        The system prompt string. Falls back to a hardcoded default if the node
        is not found in the registry.
    """
    _load_prompts()

    if node_name in _prompt_cache:
        return _prompt_cache[node_name]

    # Fall back to hardcoded default
    if node_name in _DEFAULTS:
        return _DEFAULTS[node_name]

    # Unknown node — return a generic prompt
    return f"You are a helpful AI assistant working on the '{node_name}' task."


def get_all_prompts() -> Dict[str, str]:
    """Returns all loaded prompts as a dict."""
    _load_prompts()
    return dict(_prompt_cache)


def reload():
    """Forces a reload from the JSON file. Useful for hot-reloading during dev."""
    global _loaded
    _loaded = False
    _prompt_cache.clear()
    _load_prompts()
