"""Start the local TimeCapsule API and Next.js dashboard together."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


DASHBOARD = Path(__file__).parent
EXAMPLE_ROOT = DASHBOARD.parent


def wait_for_api(port: int, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            time.sleep(0.2)
    raise RuntimeError(f"dashboard API did not start on port {port}")


def stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the TimeCapsule API and Next.js dashboard")
    parser.add_argument("--run", type=Path, default=Path("runs/latest.json"))
    parser.add_argument("--api-port", type=int, default=8766)
    parser.add_argument("--frontend-port", type=int, default=3000)
    args = parser.parse_args()
    run_path = args.run if args.run.is_absolute() else EXAMPLE_ROOT / args.run
    api = subprocess.Popen([
        sys.executable,
        str(DASHBOARD / "server.py"),
        "--run",
        str(run_path),
        "--port",
        str(args.api_port),
    ], cwd=EXAMPLE_ROOT)
    frontend_env = os.environ.copy()
    frontend_env["TIMECAPSULE_API_ORIGIN"] = f"http://127.0.0.1:{args.api_port}"
    frontend = None
    try:
        wait_for_api(args.api_port)
        frontend = subprocess.Popen([
            "npm",
            "run",
            "dev",
            "--",
            "--hostname",
            "127.0.0.1",
            "--port",
            str(args.frontend_port),
        ], cwd=DASHBOARD, env=frontend_env)
        print(f"TimeCapsule dashboard: http://127.0.0.1:{args.frontend_port}", flush=True)
        print("Press Ctrl-C to stop the API and frontend.", flush=True)
        while api.poll() is None and frontend.poll() is None:
            time.sleep(0.5)
        return api.returncode or frontend.returncode or 0
    except KeyboardInterrupt:
        return 0
    finally:
        if frontend is not None:
            stop(frontend)
        stop(api)


if __name__ == "__main__":
    raise SystemExit(main())
