import requests
import json
import time
import sys

print("Triggering video generation for subject: 'Artificial Intelligence'...")
start_res = requests.post("http://127.0.0.1:8000/api/start", json={"subject": "Artificial Intelligence"})
print(f"API Start Response: {start_res.json()}")

if not start_res.json().get("success"):
    print("Failed to start pipeline. Exiting.")
    sys.exit(1)

print("\n--- STREAMING REAL-TIME AGENT LOGS ---")
response = requests.get("http://127.0.0.1:8000/api/stream", stream=True)
for line in response.iter_lines():
    if line:
        decoded_line = line.decode('utf-8')
        if decoded_line.startswith("data:"):
            payload = json.loads(decoded_line[5:])
            if payload.get("type") == "log":
                print(f"[{payload['active_step'].upper()}] {payload['content']}")
            elif payload.get("type") == "config":
                print("\n[SUCCESS] Final Visual Director config received!")
                print(json.dumps(payload["config"], indent=2)[:500] + "...\n(Truncated for console readability)")
                break
            
            # If the setup or logs show a failure state, detect it
            if payload.get("active_step") == "failed":
                print("\n[FAILURE] Pipeline failed!")
                break
