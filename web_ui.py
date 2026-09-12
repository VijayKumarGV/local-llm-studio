"""
Local LLM Web Interface.
Runs a zero-dependency web server on http://127.0.0.1:8080 that communicates directly
with Ollama. Provides a sleek dark-mode UI with streaming responses, temperature
controls, custom system prompts, and model selection.
"""

import http.server
import socketserver
import json
import urllib.request
import urllib.error
import os
import sys

PORT = 8080
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class StudioHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def do_GET(self):
        if self.path == "/api/tags":
            self.proxy_get(f"{OLLAMA_HOST}/api/tags")
        elif self.path == "/" or self.path == "/index.html":
            return super().do_GET()
        else:
            return super().do_GET()

    def do_POST(self):
        if self.path == "/api/chat":
            self.proxy_chat_stream()
        else:
            self.send_error(404, "Endpoint not found")

    def proxy_get(self, url):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def proxy_chat_stream(self):
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len)

        try:
            url = f"{OLLAMA_HOST}/api/chat"
            req = urllib.request.Request(
                url,
                data=post_body,
                headers={"Content-Type": "application/json"}
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            with urllib.request.urlopen(req, timeout=120) as resp:
                for line in resp:
                    if line:
                        self.wfile.write(b"data: " + line.strip() + b"\n\n")
                        self.wfile.flush()
        except Exception as e:
            err_msg = json.dumps({"error": str(e)}).encode()
            self.wfile.write(b"data: " + err_msg + b"\n\n")
            self.wfile.flush()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def run():
    os.makedirs(STATIC_DIR, exist_ok=True)
    with socketserver.TCPServer(("", PORT), StudioHandler) as httpd:
        print(f"\n=======================================================")
        print(f"  Local LLM Studio Web UI running at:")
        print(f"  --> http://localhost:{PORT}")
        print(f"=======================================================\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down web server...")
            httpd.server_close()


if __name__ == "__main__":
    run()
