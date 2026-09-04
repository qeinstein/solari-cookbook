"""Run the TimeCapsule demo with one command.

Local mode opens the checked-in proof. Cloud mode runs a real Solari-backed
agent first, then opens the same dashboard against the fresh cloud artifact.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


EXAMPLE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = EXAMPLE_ROOT.parents[1]
DEFAULT_LOCAL_RUN = Path("demo/solari-canonical.json")


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE entries without executing the file as shell code."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not (key[0].isalpha() or key[0] == "_"):
            continue
        if not all(char.isalnum() or char == "_" for char in key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def require_cloud_keys(agent: str) -> bool:
    if not (os.environ.get("TIMECAPSULE_CLOUD_KEY") or os.environ.get("SOLARI_API_KEY")):
        print(
            "Cloud mode needs a Solari key. Add TIMECAPSULE_CLOUD_KEY or "
            "SOLARI_API_KEY to the repository .env file.",
            file=sys.stderr,
        )
        return False
    if agent == "model" and not os.environ.get("OPENROUTER_API_KEY"):
        print(
            "Model mode needs OPENROUTER_API_KEY in the repository .env file.",
            file=sys.stderr,
        )
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the TimeCapsule demo and start its API and dashboard together."
    )
    parser.add_argument(
        "--cloud",
        action="store_true",
        help="run a fresh cloud-backed Solari agent before opening the dashboard",
    )
    parser.add_argument(
        "--agent",
        choices=("model", "policy"),
        default="model",
        help="cloud agent to run; model is the default for the live demo",
    )
    parser.add_argument(
        "--model",
        default="openai/gpt-5.4-mini",
        help="OpenRouter model ID used with --agent model",
    )
    parser.add_argument("--futures", type=int, default=1)
    parser.add_argument("--seed", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--max-environments", type=int, default=2)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--allow-untested-model", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run", type=Path, help="saved local or cloud run to show")
    parser.add_argument("--api-port", type=int, default=8766)
    parser.add_argument("--frontend-port", type=int, default=3000)
    return parser


def cloud_run(args: argparse.Namespace) -> Path | None:
    load_dotenv(REPO_ROOT / ".env")
    if not require_cloud_keys(args.agent):
        return None

    output = args.output or Path(f"runs/cloud-{args.agent}-demo.json")
    command = [
        sys.executable,
        str(EXAMPLE_ROOT / "main.py"),
        "cloud",
        "--agent",
        args.agent,
        "--futures",
        str(args.futures),
        "--seed",
        str(args.seed),
        "--concurrency",
        str(args.concurrency),
        "--max-environments",
        str(args.max_environments),
        "--temperature",
        str(args.temperature),
        "--output",
        str(output),
    ]
    if args.agent == "model":
        command.extend(["--model", args.model])
        if args.allow_untested_model:
            command.append("--allow-untested-model")

    print(f"Starting live Solari {args.agent} run…", flush=True)
    completed = subprocess.run(command, cwd=EXAMPLE_ROOT, check=False)
    if completed.returncode:
        print("Cloud run failed; the dashboard was not started.", file=sys.stderr)
        return None

    run_path = output if output.is_absolute() else EXAMPLE_ROOT / output
    if not run_path.is_file():
        print(f"Cloud run completed but did not create {run_path}.", file=sys.stderr)
        return None
    return output


def main() -> int:
    args = build_parser().parse_args()
    load_dotenv(REPO_ROOT / ".env")

    if args.cloud:
        run_path = cloud_run(args)
        if run_path is None:
            return 1
    else:
        run_path = args.run or DEFAULT_LOCAL_RUN

    dashboard_command = [
        sys.executable,
        str(EXAMPLE_ROOT / "dashboard" / "dev.py"),
        "--run",
        str(run_path),
        "--api-port",
        str(args.api_port),
        "--frontend-port",
        str(args.frontend_port),
    ]
    print("Starting the API and dashboard together…", flush=True)
    return subprocess.run(dashboard_command, cwd=EXAMPLE_ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
