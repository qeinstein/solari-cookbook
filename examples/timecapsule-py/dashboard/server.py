from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
from datetime import datetime
from pathlib import Path
import sys
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parents[1]))
from timecapsule.core import comparison, minimize, save_future, Event


def entry_events(entry):
    return [Event(datetime.fromisoformat(item["at"]), item["kind"], item.get("payload", {})) for item in entry["events"]]


def make_handler(run_path, regression_dir=None):
    regression_dir = regression_dir or Path(__file__).parents[1] / "regressions"

    class Handler(BaseHTTPRequestHandler):
        def body(self, value, status=200, content_type="application/json"):
            raw = value if isinstance(value, bytes) else value.encode()
            self.send_response(status); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/run": self.body(run_path.read_bytes() if run_path.exists() else b'{"futures":[]}')
            elif path in {"/", "/index.html"}: self.body((Path(__file__).parent / "index.html").read_bytes(), content_type="text/html")
            else: self.send_error(404)

        def do_POST(self):
            parts = urlparse(self.path).path.strip("/").split("/")
            if len(parts) != 4 or parts[:2] != ["api", "futures"] or parts[3] not in {"compare", "minimize", "regress"}:
                self.body(b'{"error":"not found"}', 404); return
            data = json.loads(run_path.read_text()) if run_path.exists() else {"futures": []}
            entry = next((item for item in data["futures"] if item["future_id"] == parts[2]), None)
            if entry is None: self.body(b'{"error":"future not found"}', 404); return
            events = entry_events(entry)
            if parts[3] == "minimize":
                events = minimize(events); output = run_path.parent / f"{parts[2]}-minimal.json"; result = comparison(events); save_future(output, events, result)
                self.body(json.dumps({"events": len(events), "comparison": result, "saved": str(output)}))
            elif parts[3] == "regress":
                regression_path = regression_dir / f"{parts[2]}.json"
                result = comparison(events); save_future(regression_path, events, result)
                self.body(json.dumps({"events": len(events), "comparison": result, "regression": str(regression_path)}))
            else: self.body(json.dumps({"comparison": comparison(events)}))

        def log_message(self, *_): pass
    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--run", type=Path, default=Path("runs/latest.json")); parser.add_argument("--port", type=int, default=8766); args = parser.parse_args()
    print(f"future tree listening on http://127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(args.run)).serve_forever()
