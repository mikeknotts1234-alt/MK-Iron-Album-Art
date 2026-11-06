"""Run the editor raster suite and local HTTP contract checks. No provider calls."""
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import patch

import server

ROOT = Path(__file__).resolve().parent


class QuietEditor(server.Editor):
    def log_message(self, *args):
        pass


def bridge_checks():
    results = []
    with server.ThreadingHTTPServer(("127.0.0.1", 0), QuietEditor) as httpd:
        port = httpd.server_port
        host = f"127.0.0.1:{port}"
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(server, "HOST", host), patch.dict(os.environ, {"GEMINI_API_KEY": ""}), patch.object(server, "generate", return_value="fixture-art") as mock:
                cases = [
                    ("missing key", host, {"prompt": "mountains"}, 503),
                    ("cross-origin request", "example.invalid", {"prompt": "mountains"}, 403),
                    ("empty prompt", host, {"prompt": " "}, 400),
                    ("valid request with simulated provider", host, {"prompt": "mountains"}, 200),
                ]
                for name, origin, payload, expected in cases:
                    if expected == 200:
                        os.environ["GEMINI_API_KEY"] = "unit-test-placeholder"
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    try:
                        conn.request("POST", "/api/generate", json.dumps(payload),
                                     {"Origin": "http://" + origin, "Content-Type": "application/json"})
                        response = conn.getresponse()
                        body = json.loads(response.read())
                        ok = response.status == expected
                        if expected == 200:
                            ok = ok and body == {"image": "fixture-art"} and mock.call_count == 1
                        else:
                            ok = ok and mock.call_count == 0
                        results.append({"name": name, "pass": ok, "http_status": response.status})
                    finally:
                        conn.close()
        finally:
            httpd.shutdown()
            thread.join()
    return results


def main():
    try:
        proc = subprocess.run(["node", str(ROOT / "qa" / "verify.cjs")], capture_output=True, text=True, timeout=90)
        editor = json.loads(proc.stdout)
        editor["pass"] = editor["pass"] and proc.returncode == 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        editor = {"pass": False, "error": f"Editor runner unavailable ({exc}). See START-HERE.txt for prerequisites."}
    try:
        bridge = bridge_checks()
    except OSError as exc:
        bridge = [{"name": "local HTTP suite", "pass": False, "error": str(exc)}]
    passed = editor["pass"] and all(item["pass"] for item in bridge)
    print(json.dumps({"pass": passed, "editor": editor, "bridge": bridge,
                      "untested": ["physical phone", "native browser download UI", "live Gemini"]}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
