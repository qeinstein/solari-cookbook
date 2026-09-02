"""TimeCapsule CLI: coverage-guided local proof and isolated execution."""

import argparse
import asyncio
from pathlib import Path
import sys

from timecapsule.benchmark import print_benchmark, run_benchmark, save_benchmark
from timecapsule.core import comparison, load_future, minimize_for_violation, save_future
from timecapsule.runner import future_coverage, local_run
from timecapsule.solari_runner import solari_run, timestamp_observed_trace


def saved_future_command(mode: str, path: Path):
    events = load_future(path)
    if mode == "replay":
        result = comparison(events)["original"]
        print(f"{path}: {result}")
        return 0 if result == "FAIL" else 1
    if mode == "minimize":
        minimal = minimize_for_violation(events)
        output = path.with_name(path.stem + "-minimal.json")
        save_future(output, minimal)
        print(f"Minimized {len(events)} events to {len(minimal)}")
        print(f"Saved: {output}")
        return 0
    result = comparison(events)
    print(f"Original: {result['original']}")
    print(f"Patched: {result['patched']}")
    return 0 if result == {"original": "FAIL", "patched": "PASS"} else 1


def regress(directory: Path):
    paths = sorted(directory.glob("*.json"))
    if not paths:
        print(f"No regression futures found in {directory}", file=sys.stderr)
        return 1
    failures = 0
    for path in paths:
        result = comparison(load_future(path))
        passed = result == {"original": "FAIL", "patched": "PASS"}
        print(f"{'PASS' if passed else 'FAIL'} {path.name}")
        failures += not passed
    print(f"Regression futures: {len(paths) - failures}/{len(paths)} passed")
    return 1 if failures else 0


def parser():
    root = argparse.ArgumentParser(description="Explore collections-agent futures")
    commands = root.add_subparsers(dest="mode", required=True)
    local = commands.add_parser("run", aliases=["local"], help="coverage-guided local search")
    local.add_argument("--futures", type=int, default=25)
    local.add_argument("--seed", type=int, default=0)
    local.add_argument("--output", type=Path, default=Path("runs/latest.json"))
    cloud = commands.add_parser(
        "cloud",
        aliases=["solari"],
        help="run isolated futures in a managed browser runtime",
    )
    cloud.add_argument("--futures", type=int, default=3)
    cloud.add_argument("--seed", type=int, default=0)
    cloud.add_argument("--concurrency", type=int, default=1)
    cloud.add_argument("--max-environments", type=int, default=20)
    cloud.add_argument(
        "--agent",
        choices=("policy", "model"),
        default="policy",
        help="deterministic built-in policy (default) or an OpenRouter model agent",
    )
    cloud.add_argument(
        "--model",
        metavar="MODEL_ID",
        help="OpenRouter model ID; omit in a terminal to choose from the curated list",
    )
    cloud.add_argument("--temperature", type=float, default=0.2)
    cloud.add_argument(
        "--allow-untested-model",
        action="store_true",
        help="allow an OpenRouter model ID outside the curated tested list",
    )
    cloud.add_argument("--output", type=Path, default=Path("runs/cloud-latest.json"))
    benchmark = commands.add_parser("benchmark", help="matched random vs coverage-guided search benchmark")
    benchmark.add_argument("--trials", type=int, default=200)
    benchmark.add_argument("--budget", type=int, default=128)
    benchmark.add_argument("--seed", type=int, default=0)
    benchmark.add_argument("--output", type=Path, default=Path("runs/search-benchmark.json"))
    for mode in ("replay", "minimize", "compare"):
        command = commands.add_parser(mode, help=f"{mode} a saved future")
        command.add_argument("future", type=Path)
    regression = commands.add_parser("regress", help="run checked-in regression futures")
    regression.add_argument("--directory", type=Path, default=Path("regressions"))
    return root


def main():
    args = parser().parse_args()
    if args.mode in {"run", "local"}:
        local_run(args.futures, args.seed, args.output)
    elif args.mode in {"cloud", "solari"}:
        asyncio.run(solari_run(
            args.futures,
            args.seed,
            args.output,
            args.concurrency,
            args.max_environments,
            args.agent,
            args.model,
            args.temperature,
            args.allow_untested_model,
        ))
    elif args.mode == "benchmark":
        report = run_benchmark(args.trials, args.budget, args.seed)
        print_benchmark(report)
        save_benchmark(args.output, report)
        print(f"Benchmark saved: {args.output}")
    elif args.mode == "regress":
        raise SystemExit(regress(args.directory))
    else:
        raise SystemExit(saved_future_command(args.mode, args.future))


if __name__ == "__main__":
    main()
