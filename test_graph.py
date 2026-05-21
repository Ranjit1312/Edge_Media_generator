import json
import sys
import os

# Safely reconfigure console stdout and stderr for UTF-8 representation
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

def safe_print(text):
    try:
        print(text)
    except UnicodeEncodeError:
        try:
            print(text.encode('ascii', errors='replace').decode('ascii'))
        except Exception:
            print("[Encoding Error: Unable to print log line]")

from app.agent_engine import build_agent_graph, AgentState

def run_test():
    safe_print("Initializing LangGraph Multi-Agent Test...")
    graph = build_agent_graph()
    
    initial_state = {
        "subject": "Artificial Intelligence",
        "search_queries": ["Artificial Intelligence"],
        "model_name": "gemma4:e4b",
        "scraping_attempts": 0,
        "raw_news": [],
        "verified_news": [],
        "final_scripts": [],
        "animation_config": {},
        "logs": []
    }
    
    safe_print("Running State Machine pipeline...")
    try:
        from app.checkpointer import make_thread_config
        thread_config = make_thread_config("test_thread")
        final_state = graph.invoke(initial_state, config=thread_config)
        
        safe_print("\n=== PIPELINE RUN LOGS ===")
        for log in final_state.get("logs", []):
            safe_print(f"- {log}")
            
        safe_print("\n=== GENERATED ANIMATION CONFIG ===")
        try:
            config_str = json.dumps(final_state.get("animation_config", {}), indent=2)
            safe_print(config_str)
        except Exception as e:
            safe_print(f"Error printing animation config: {e}")
        
        # Write directly to static folder so the browser can load it
        static_config = os.path.join("app", "static", "config.json")
        with open(static_config, "w", encoding="utf-8") as f:
            json.dump(final_state.get("animation_config", {}), f, indent=2)
            
        safe_print(f"\n[SUCCESS] Storyboard written to {static_config}!")
    except Exception as e:
        safe_print(f"\n[FATAL ERROR] State Machine failed to execute: {e}")

if __name__ == "__main__":
    run_test()
