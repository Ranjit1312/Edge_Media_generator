"""
Multi-Model Ollama Fleet Registry — Per-Node Assignment
========================================================
Dual-mode architecture:

PRODUCTION (DEV_MODE=false, default):
  Hardcoded 2-model split. Zero config files read.
  - gemma2:2b  → Editor (fast analysis, fact-checking)
  - gemma4:e4b → Scriptwriter + Director (creative, JSON structure)

DEVELOPER (DEV_MODE=true):
  Configurable per-node model assignment for A/B testing.
  Resolution priority (highest wins):
    1. Environment variable: MODEL_EDITOR=qwen3:4b
    2. Config file: prompts/models_config.json
    3. Production catalog fallback
"""
from __future__ import annotations

import os
import json
import time
import threading
import urllib.request
from pathlib import Path
from typing import Dict, Optional, List, Any

# ─── Production Catalog (hardcoded, no config files) ─────────────────────────

PRODUCTION_CATALOG: Dict[str, Dict[str, str]] = {
    "researcher_fallback": {"primary": "gemma2:2b",  "fallback": "gemma4:e4b"},
    "editor":              {"primary": "gemma2:2b",  "fallback": "gemma4:e4b"},
    "scriptwriter":        {"primary": "gemma4:e4b", "fallback": "gemma2:2b"},
    "director":            {"primary": "gemma4:e4b", "fallback": "gemma2:2b"},
}

# Production fleet — always pulled
PRODUCTION_FLEET: List[str] = ["gemma2:2b", "gemma4:e4b"]

# ─── State ─────────────────────────────────────────────────────────────────────

_available_models: set = set()
_pull_lock = threading.Lock()
_pull_status: Dict[str, str] = {}
_dev_overrides: Dict[str, str] = {}  # DEV_MODE per-node overrides
_dev_mode: bool = False
_ollama_url = "http://localhost:11434"
_config_loaded = False


# ─── DEV_MODE Config Loading ──────────────────────────────────────────────────

def _load_dev_config(force: bool = False):
    """Loads per-node model overrides from prompts/models_config.json when DEV_MODE=true."""
    global _dev_overrides, _dev_mode, _config_loaded

    if _config_loaded and not force:
        return

    # Check config file first
    config_path = Path(__file__).parent.parent / "prompts" / "models_config.json"
    config_dev_mode = False
    config_node_models = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            config_dev_mode = data.get("dev_mode", False)
            config_node_models = data.get("node_models", {})
        except Exception as e:
            print(f"[MODEL_REGISTRY] Failed to read models_config.json: {e}", flush=True)

    # ENV takes priority, otherwise config file
    env_dev_mode = os.environ.get("DEV_MODE", "false").lower() in ("true", "1", "yes")
    _dev_mode = env_dev_mode or config_dev_mode

    _dev_overrides.clear()
    if _dev_mode:
        print("[MODEL_REGISTRY] Developer mode is active.", flush=True)
        # Load from config file
        _dev_overrides.update(config_node_models)
        
        # Environment variables override config file (highest priority)
        env_map = {
            "MODEL_RESEARCHER": "researcher_fallback",
            "MODEL_EDITOR": "editor",
            "MODEL_SCRIPTWRITER": "scriptwriter",
            "MODEL_DIRECTOR": "director",
        }
        for env_key, node_name in env_map.items():
            env_val = os.environ.get(env_key)
            if env_val:
                _dev_overrides[node_name] = env_val
                print(f"[MODEL_REGISTRY] Env override: {env_key}={env_val} -> node '{node_name}'", flush=True)
        
        if _dev_overrides:
            print(f"[MODEL_REGISTRY] Active dev overrides: {_dev_overrides}", flush=True)
    else:
        print("[MODEL_REGISTRY] Production mode - hardcoded 2-model split active.", flush=True)

    _config_loaded = True


def save_dev_config(dev_mode: bool, node_models: Dict[str, str]) -> bool:
    """Saves the developer mode config back to prompts/models_config.json."""
    config_path = Path(__file__).parent.parent / "prompts" / "models_config.json"
    try:
        # Load existing data first to preserve other keys (like extra_models_to_pull)
        data = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
                
        data["dev_mode"] = dev_mode
        data["node_models"] = node_models
        
        # Ensure directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            
        # Force reload config
        _load_dev_config(force=True)
        return True
    except Exception as e:
        print(f"[MODEL_REGISTRY] Failed to save dev config: {e}", flush=True)
        return False


# ─── Public API ────────────────────────────────────────────────────────────────

def get_model_for_node(node_name: str, system_default: str = "gemma4:e4b") -> str:
    """
    Returns the best available model for a given node.

    Resolution priority:
      DEV_MODE=true:
        1. Env var override (MODEL_EDITOR=xxx)
        2. Config file (prompts/models_config.json)
        3. Production catalog
      DEV_MODE=false:
        1. Production catalog primary (if available)
        2. Production catalog fallback (if available)
        3. system_default
    """
    _load_dev_config()
    if not _available_models:
        refresh_available_models()

    # In DEV_MODE, check overrides first
    if _dev_mode and node_name in _dev_overrides:
        override_model = _dev_overrides[node_name]
        if override_model in _available_models:
            return override_model
        else:
            print(
                f"[MODEL_REGISTRY] Dev override '{override_model}' for node '{node_name}' "
                f"not yet available. Falling back to production catalog.",
                flush=True
            )

    # Production catalog lookup
    entry = PRODUCTION_CATALOG.get(node_name)
    if not entry:
        return system_default

    primary = entry["primary"]
    fallback = entry["fallback"]

    if primary in _available_models:
        return primary
    if fallback in _available_models:
        return fallback

    return system_default


def get_fleet_status() -> Dict[str, Any]:
    """Returns the current status of all fleet models for the /api/models endpoint."""
    _load_dev_config()
    refresh_available_models()
    return {
        "mode": "developer" if _dev_mode else "production",
        "production_catalog": PRODUCTION_CATALOG,
        "dev_overrides": _dev_overrides if _dev_mode else {},
        "fleet_models": get_all_fleet_models(),
        "available": sorted(list(_available_models)),
        "pull_status": dict(_pull_status),
        "node_assignments": {
            node: get_model_for_node(node) for node in PRODUCTION_CATALOG
        }
    }


def get_all_fleet_models() -> List[str]:
    """Returns all models that should be pulled (production + dev extras)."""
    _load_dev_config()

    models = list(PRODUCTION_FLEET)

    if _dev_mode:
        # Add models referenced in dev overrides
        for model in _dev_overrides.values():
            if model not in models:
                models.append(model)

        # Add extra models from config file
        config_path = Path(__file__).parent.parent / "prompts" / "models_config.json"
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for extra in data.get("extra_models_to_pull", []):
                    if extra not in models:
                        models.append(extra)
            except Exception:
                pass

    return models


def refresh_available_models():
    """Queries Ollama API to discover which models are already pulled."""
    global _available_models
    try:
        req = urllib.request.Request(f"{_ollama_url}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = data.get("models", [])
            names = set()
            for m in models:
                name = m.get("name", "")
                # Normalize tag formats
                base_name = name.replace(":latest", "")
                names.add(base_name)
                names.add(name)
            _available_models = names
            print(f"[MODEL_REGISTRY] Available models: {sorted(names)}", flush=True)
    except Exception as e:
        print(f"[MODEL_REGISTRY] Could not query Ollama tags: {e}", flush=True)


def pull_single_model(model_name: str) -> bool:
    """Pulls a single model via Ollama API. Blocks until complete."""
    _pull_status[model_name] = "pulling"
    print(f"[MODEL_REGISTRY] Pulling model: {model_name}...", flush=True)

    try:
        payload = json.dumps({"name": model_name, "stream": False}).encode("utf-8")
        req = urllib.request.Request(
            f"{_ollama_url}/api/pull",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=1800) as resp:
            resp.read()

        _available_models.add(model_name)
        _pull_status[model_name] = "ready"
        print(f"[MODEL_REGISTRY] [OK] Model '{model_name}' pulled successfully.", flush=True)
        return True

    except Exception as e:
        _pull_status[model_name] = f"failed: {e}"
        print(f"[MODEL_REGISTRY] [ERROR] Failed to pull '{model_name}': {e}", flush=True)
        return False


def unload_current_model():
    """
    Unloads the currently loaded model from GPU VRAM.
    Called between model groups to ensure clean VRAM state before loading next model.
    """
    try:
        # Send a generate request with keep_alive=0 to trigger unload
        # This is the Ollama-recommended way to unload
        payload = json.dumps({
            "model": "",
            "keep_alive": 0
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{_ollama_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception:
            pass  # Unload may return errors for empty model, that's OK
        print("[MODEL_REGISTRY] Sent VRAM unload signal.", flush=True)
    except Exception as e:
        print(f"[MODEL_REGISTRY] Unload signal failed ({e}) - non-critical.", flush=True)


def ensure_fleet_ready_blocking():
    """
    Blocking fleet puller. Pulls all required models sequentially.
    Called during startup — pipeline WILL NOT start until all models are ready.
    """
    _load_dev_config()
    refresh_available_models()

    all_models = get_all_fleet_models()
    missing = [m for m in all_models if m not in _available_models]

    if not missing:
        print(f"[MODEL_REGISTRY] All {len(all_models)} fleet models already available.", flush=True)
        return True

    print(f"[MODEL_REGISTRY] Pulling {len(missing)} missing model(s): {missing}", flush=True)

    success = True
    for model in missing:
        if not pull_single_model(model):
            success = False
        time.sleep(1)

    refresh_available_models()

    # Verify all production models are present
    for prod_model in PRODUCTION_FLEET:
        if prod_model not in _available_models:
            print(f"[MODEL_REGISTRY] [WARNING] Production model '{prod_model}' still missing!", flush=True)
            success = False

    if success:
        print("[MODEL_REGISTRY] Fleet ready. All models verified.", flush=True)
    else:
        print("[MODEL_REGISTRY] Fleet partially ready. Some models failed to pull.", flush=True)

    return success
