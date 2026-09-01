from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
from datetime import datetime
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parents[1]))
from timecapsule.core import (
    Event,
    comparison,
    execute,
    future_fingerprint,
    minimize,
    save_future,
    violation_snapshot,
)


def entry_events(entry):
    return [Event(datetime.fromisoformat(item["at"]), item["kind"], item.get("payload", {})) for item in entry["events"]]


def read_run(run_path):
    if not run_path.exists():
        return {"futures": []}
    data = json.loads(run_path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("futures", []), list):
        raise ValueError("run file must contain a futures array")
    return data


def make_handler(run_path, regression_dir=None):
    regression_dir = regression_dir or Path(__file__).parents[1] / "regressions"

    class Handler(BaseHTTPRequestHandler):
        def body(self, value, status=200, content_type="application/json"):
            raw = value if isinstance(value, bytes) else value.encode()
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def error(self, message, status=400):
            self.body(json.dumps({"error": message}), status)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/run":
                try:
                    self.body(json.dumps(read_run(run_path)))
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    self.error(f"run unavailable: {exc}", 503)
            elif path == "/health":
                self.body(json.dumps({"status": "ok", "run_exists": run_path.exists()}))
            else:
                self.error("not found", 404)

        def do_POST(self):
            parts = urlparse(self.path).path.strip("/").split("/")
            if (len(parts) != 4 or parts[:2] != ["api", "futures"]
                    or parts[3] not in {"compare", "minimize", "regress"}):
                self.error("not found", 404)
                return
            if not re.fullmatch(r"[A-Za-z0-9._-]+", parts[2]):
                self.error("invalid future id", 400)
                return
            try:
                data = read_run(run_path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                self.error(f"run unavailable: {exc}", 503)
                return
            entry = next((item for item in data["futures"] if item["future_id"] == parts[2]), None)
            if entry is None:
                self.error("future not found", 404)
                return
            try:
                events = entry_events(entry)
                if parts[3] == "minimize":
                    original_events = events
                    events = minimize(original_events)
                    output = run_path.parent / f"{parts[2]}-minimal.json"
                    result = comparison(events)
                    save_future(output, events, result)
                    self.body(json.dumps({
                        "events": len(events),
                        "before_events": len(original_events),
                        "removed_events": len(original_events) - len(events),
                        "original_events": [event.as_dict() for event in original_events],
                        "minimal_events": [event.as_dict() for event in events],
                        "input_hash": future_fingerprint(original_events),
                        "minimal_input_hash": future_fingerprint(events),
                        "minimal_violation": violation_snapshot(execute(events)),
                        "comparison": result,
                        "saved": str(output),
                    }))
                elif parts[3] == "regress":
                    events = minimize(events)
                    regression_path = regression_dir / f"{parts[2]}.json"
                    result = comparison(events)
                    save_future(regression_path, events, result)
                    self.body(json.dumps({
                        "events": len(events),
                        "minimal_events": [event.as_dict() for event in events],
                        "minimal_input_hash": future_fingerprint(events),
                        "minimal_violation": violation_snapshot(execute(events)),
                        "comparison": result,
                        "regression": str(regression_path),
                    }))
                else:
                    fingerprint = future_fingerprint(events)
                    self.body(json.dumps({
                        "comparison": comparison(events),
                        "input_hash": fingerprint,
                        "same_input": True,
                    }))
            except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
                self.error(f"future action failed: {exc}", 422)

        def log_message(self, *_): pass
    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--run", type=Path, default=Path("runs/latest.json")); parser.add_argument("--port", type=int, default=8766); args = parser.parse_args()
    print(f"future tree listening on http://127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(args.run)).serve_forever()
