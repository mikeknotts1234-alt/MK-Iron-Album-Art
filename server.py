"""Private, loopback-only Gemini bridge for the album editor."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request, error

HOST = "127.0.0.1:8769"
MODEL_URL = "https://generativelanguage.googleapis.com/v1/models/gemini-3.1-flash-image:generateContent"
slot = threading.Lock()


def generate(prompt):
    payload = {"contents": [{"parts": [{"text": "Create square album cover art without lettering: " + prompt}]}],
               "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
    req = request.Request(MODEL_URL, data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    with request.urlopen(req, timeout=100) as response:
        data = json.load(response)
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            image = part.get("inlineData", {})
            if image.get("mimeType") in ("image/jpeg", "image/png", "image/webp") and image.get("data"):
                return "data:" + image["mimeType"] + ";base64," + image["data"]
    raise ValueError("No image returned")


class Editor(BaseHTTPRequestHandler):
    def reply(self, status, data, mime="application/json"):
        body = json.dumps(data).encode() if mime == "application/json" else data
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("Host") != HOST:
            return self.reply(403, {})
        if self.path in ("/", "/index.html"):
            return self.reply(200, Path(__file__).with_name("index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/status":
            return self.reply(200, {"ready": bool(os.getenv("GEMINI_API_KEY"))})
        self.reply(404, {})

    def do_POST(self):
        if self.path != "/api/generate":
            return self.reply(404, {})
        if self.headers.get("Host") != HOST or self.headers.get("Origin") != "http://" + HOST:
            return self.reply(403, {"error": "Open the editor at http://" + HOST})
        if self.headers.get_content_type() != "application/json":
            return self.reply(415, {})
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 12000:
                return self.reply(413, {})
            body = json.loads(self.rfile.read(length))
            prompt = body.get("prompt") if isinstance(body, dict) else None
            if not isinstance(prompt, str) or not 0 < len(prompt.strip()) <= 1200:
                raise ValueError()
        except (ValueError, UnicodeError):
            return self.reply(400, {"error": "Enter a description of up to 1200 characters."})
        if not os.getenv("GEMINI_API_KEY"):
            return self.reply(503, {"error": "Start the server with a Gemini API key."})
        if not slot.acquire(blocking=False):
            return self.reply(429, {"error": "An image is already being generated."})
        try:
            image = generate(prompt.strip())
        except error.HTTPError as exc:
            message = {429: "Gemini quota reached. Check your quota before retrying.",
                       403: "Gemini denied access. Check the key, model access and billing.",
                       400: "Gemini rejected the request. Check the key and description."}
            return self.reply(502, {"error": message.get(exc.code, f"Gemini returned HTTP {exc.code}.")})
        except (ValueError, OSError):
            return self.reply(502, {"error": "Gemini returned no usable image. Check connectivity or try a different description."})
        finally:
            slot.release()
        self.reply(200, {"image": image})


if __name__ == "__main__":
    from getpass import getpass
    if not os.getenv("GEMINI_API_KEY"):
        os.environ["GEMINI_API_KEY"] = getpass("Gemini key (hidden, Enter for offline editor): ").strip()
    with ThreadingHTTPServer(("127.0.0.1", 8769), Editor) as server:
        print("Open http://" + HOST + " in your browser. Press Ctrl+C to stop.", flush=True)
        server.serve_forever()
