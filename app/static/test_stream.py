import requests
import time

print("Listening to /api/stream SSE...")
try:
    response = requests.get("http://127.0.0.1:8000/api/stream", stream=True, timeout=10)
    start_time = time.time()
    for line in response.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            if decoded_line.startswith("data:"):
                print(decoded_line)
        # Stop after 3 seconds
        if time.time() - start_time > 3:
            break
except Exception as e:
    print(f"Error reading SSE stream: {e}")
