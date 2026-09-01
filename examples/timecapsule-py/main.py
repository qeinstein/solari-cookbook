"""TimeCapsule runner: local proof plus a real Solari execution mode."""

import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import sys

from timecapsule.core import (
    INVARIANT_ID,
    comparison,
    execute,
    future_fingerprint,
    generate_future,
    invariant_holds,
    load_future,
    minimize,
    observed_invariant_holds,
    observed_violation,
    save_future,
    temporal_windows,
    violation_snapshot,
)

ROOT = Path(__file__).parent
TEMPORAL_WINDOWS = {
    "before_payment": "Wakeup before payment",
    "stale_window": "Wakeup in stale CRM window",
    "after_webhook": "Wakeup after webhook",
}


def event_span_days(events):
    """Return the measured elapsed time covered by one generated future."""
    if len(events) < 2:
        return 0
    return (events[-1].at - events[0].at).total_seconds() / 86400


def future_coverage(event_sequences):
    """Summarize which meaningful temporal windows the exploration exercised."""
    counts = {window: 0 for window in TEMPORAL_WINDOWS}
    for events in event_sequences:
        for window in temporal_windows(events):
            counts[window] += 1
    covered = [
        {"id": window, "label": label, "futures": counts[window]}
        for window, label in TEMPORAL_WINDOWS.items()
        if counts[window]
    ]
    return {"covered": len(covered), "possible": len(TEMPORAL_WINDOWS), "patterns": covered}


async def goto_preview(page, preview_url: str):
    """Wait briefly for the sandbox server to bind before driving the UI."""
    for attempt in range(8):
        try:
            await page.goto(preview_url)
            return
        except Exception:
            if attempt == 7:
                raise
            await asyncio.sleep(0.5)


async def click_world_action(page, selector: str, action: str):
    """Click a world control and wait until its state update has committed."""
    await page.locator(selector).click()
    sync_status = page.locator("#sync-status")
    for _ in range(40):
        state = await sync_status.get_attribute("data-state")
        completed_action = await sync_status.get_attribute("data-action")
        if state == "ready" and completed_action == action:
            return
        await asyncio.sleep(0.25)
    raise RuntimeError(f"world action did not settle: {action}")


async def read_world_trace(page):
    return json.loads(await page.locator("#trace").inner_text())


def serializable_world(world):
    return {
        "payment_status": world.payment_status,
        "invoice_status": world.invoice_status,
        "messages": [{**message, "at": message["at"].isoformat()} for message in world.messages],
        "trace": world.trace,
    }


def local_run(count: int, seed_start: int, output: Path):
    futures = []
    failures = []
    event_sequences = []
    virtual_days = 0
    for seed in range(seed_start, seed_start + count):
        events = generate_future(seed)
        event_sequences.append(events)
        virtual_days += event_span_days(events)
        world = execute(events)
        status = "PASS" if invariant_holds(world) else "FAIL"
        replay = comparison(events)
        entry = {"future_id": f"future-{seed}", "seed": seed, "agent": "original",
                 "status": status,
                 "invariant": INVARIANT_ID,
                 "input_hash": future_fingerprint(events),
                 "violation": violation_snapshot(world),
                 "comparison": replay,
                 "events": [event.as_dict() for event in events], **serializable_world(world)}
        futures.append(entry)
        if entry["status"] == "FAIL":
            failures.append((seed, events))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"run_id": f"local-{seed_start}-{seed_start + count - 1}",
                                  "execution_mode": "local",
                                  "started_at": datetime.now().astimezone().isoformat(),
                                  "futures": futures,
                                  "summary": {"explored": count, "failures": len(failures),
                                              "patched_replays": len(failures),
                                              "virtual_days": round(virtual_days, 1),
                                              "coverage": future_coverage(event_sequences)}}, indent=2) + "\n")
    print(f"Futures explored: {count}")
    print(f"Failures found: {len(failures)}")
    print(f"Run saved: {output}")
    if failures:
        seed, events = failures[0]
        minimal = minimize(events)
        minimal_path = output.parent / f"future-{seed}-minimal.json"
        save_future(minimal_path, minimal)
        result = comparison(minimal)
        print(f"First failure: future-{seed}")
        print(f"Minimal failing events: {len(minimal)}")
        print(f"Replay comparison: original={result['original']}, patched={result['patched']}")
        print(f"Minimal future saved: {minimal_path}")


async def solari_future(seed: int, fixed: bool = False, recording_dir: Path | None = None):
    """Run one future in one isolated Solari sandbox + browser pair."""
    from solari_browser import Solari
    from solari_browser.errors import SolariError
    from solari_sandbox import SandboxClient

    sandbox_client = SandboxClient(api_key=os.environ["SOLARI_API_KEY"], base_url="https://api.getsolari.com")
    async with sandbox_client:
        sandbox = await sandbox_client.create(template="base", timeout_ms=10 * 60_000)
        try:
            await sandbox.connect()
            remote_root = "/tmp/timecapsule-world"
            await sandbox.commands.run("mkdir", args=["-p", remote_root])
            await sandbox.files.write(f"{remote_root}/server.py", (ROOT / "world/server.py").read_text())
            await sandbox.files.write(f"{remote_root}/index.html", (ROOT / "world/index.html").read_text())
            await sandbox.commands.run("sh", args=["-c", f"cd {remote_root} && nohup python3 server.py >/tmp/timecapsule.log 2>&1 &"])
            preview = await sandbox.preview_url(8765)
            preview_url = preview["url"]

            async with Solari(api_key=os.environ["SOLARI_API_KEY"]) as solari:
                browser_session_id = None
                result = None
                async with await solari.launch(recording=True) as browser:
                    browser_session_id = browser.id
                    page = await browser.new_page()
                    await goto_preview(page, preview_url)
                    events = generate_future(seed)
                    await click_world_action(page, 'button[data-action="reset"]', "reset")
                    for event in events:
                        if event.kind == "customer_payment":
                            await click_world_action(page, 'button[data-action="pay"]', "pay")
                        elif event.kind == "agent_wakeup":
                            action = "fixed" if fixed else "original"
                            await click_world_action(page, f'button[data-action="agent/{action}"]', f"agent/{action}")
                        elif event.kind == "payment_webhook":
                            await click_world_action(page, 'button[data-action="webhook"]', "webhook")
                    messages = await page.locator("#messages").inner_text()
                    payment = await page.locator("#payment").inner_text()
                    crm = await page.locator("#crm").inner_text()
                    trace = await read_world_trace(page)
                    failed = not observed_invariant_holds(trace)
                    result = {"future_id": f"future-{seed}", "seed": seed, "status": "FAIL" if failed else "PASS",
                              "agent": "fixed" if fixed else "original", "sandbox_id": sandbox.sandboxId,
                              "browser_session_id": browser_session_id, "preview_url": preview_url,
                              "input_hash": future_fingerprint(events),
                              "violation": observed_violation(trace),
                              "events": [event.as_dict() for event in events],
                              "observed": {"payment": payment, "crm": crm, "messages": messages, "trace": trace}}
                    # rrweb batches recording events; let the final batch flush before release.
                    await asyncio.sleep(2)
                if recording_dir and browser_session_id:
                    recording_dir.mkdir(parents=True, exist_ok=True)
                    recording_path = recording_dir / f"future-{seed}-{'fixed' if fixed else 'original'}.ndjson"
                    for _ in range(10):
                        try:
                            replay = await solari.sessions.download_replay(browser_session_id)
                            recording_path.write_bytes(replay)
                            result["recording_status"] = "downloaded"
                            result["recording_path"] = str(recording_path)
                            result["recording_bytes"] = len(replay)
                            result["recording_events"] = len(replay.decode().splitlines())
                            break
                        except SolariError as error:
                            if error.status != 404:
                                raise
                            await asyncio.sleep(3)
                    else:
                        result["recording_status"] = "not_ready_after_30s"
                return result
        finally:
            await sandbox.kill()


async def solari_run(count: int, seed_start: int, output: Path, concurrency: int = 1):
    if not os.environ.get("SOLARI_API_KEY"):
        raise SystemExit("SOLARI_API_KEY is required for Solari mode")
    if concurrency < 1:
        raise SystemExit("--concurrency must be at least 1")
    recording_dir = output.parent / "replays"
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded_future(seed: int, fixed: bool = False):
        async with semaphore:
            return await solari_future(seed, fixed=fixed, recording_dir=recording_dir)

    results = await asyncio.gather(*(bounded_future(seed) for seed in range(seed_start, seed_start + count)))
    failing_seeds = [result["seed"] for result in results if result["status"] == "FAIL"]
    patched = await asyncio.gather(*(bounded_future(seed, fixed=True) for seed in failing_seeds))
    patched_by_seed = {result["seed"]: result for result in patched}
    for result in results:
        candidate = patched_by_seed.get(result["seed"])
        if candidate and candidate["input_hash"] != result["input_hash"]:
            raise RuntimeError(f"counterfactual input mismatch for {result['future_id']}")
        result["comparison"] = {"original": result["status"], "patched": candidate["status"] if candidate else "NOT_RUN"}
        if candidate:
            result["patched_run"] = {
                key: candidate[key]
                for key in (
                    "agent", "status", "input_hash", "sandbox_id", "browser_session_id",
                    "recording_path", "recording_bytes", "recording_events", "recording_status",
                    "observed",
                )
                if key in candidate
            }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"run_id": f"solari-{seed_start}-{seed_start + count - 1}",
                                  "execution_mode": "solari",
                                  "started_at": datetime.now().astimezone().isoformat(),
                                  "futures": results,
                                  "summary": {"explored": len(results), "failures": len(failing_seeds),
                                              "patched_replays": len(patched),
                                              "patched_passes": sum(
                                                  result["comparison"]["patched"] == "PASS"
                                                  for result in results if result["status"] == "FAIL"),
                                              "virtual_days": round(sum(event_span_days(generate_future(seed)) for seed in range(seed_start, seed_start + count)), 1),
                                              "coverage": future_coverage(
                                                  [generate_future(seed) for seed in range(seed_start, seed_start + count)])}}, indent=2) + "\n")
    print("Solari exploration")
    print(f"Isolated futures: {len(results)} (sandbox + browser per future, max concurrency {concurrency})")
    print(f"Failures found: {len(failing_seeds)}")
    print(f"Patched replays: {len(patched)}")
    print(f"Run saved: {output}")
    for result in results:
        print(f"{result['future_id']}: original={result['comparison']['original']} patched={result['comparison']['patched']} · sandbox {result['sandbox_id']} · browser {result['browser_session_id']}")


def saved_future_command(mode: str, path: Path):
    events = load_future(path)
    if mode == "replay":
        result = comparison(events)["original"]
        print(f"{path}: {result}")
        return 0 if result == "FAIL" else 1
    if mode == "minimize":
        minimal = minimize(events)
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


def main():
    parser = argparse.ArgumentParser(description="Explore collections-agent futures")
    sub = parser.add_subparsers(dest="mode", required=True)
    local = sub.add_parser("run", aliases=["local"], help="explore deterministic local futures")
    local.add_argument("--futures", type=int, default=25)
    local.add_argument("--seed", type=int, default=0)
    local.add_argument("--output", type=Path, default=Path("runs/latest.json"))
    cloud = sub.add_parser("solari", help="run isolated futures in Solari")
    cloud.add_argument("--futures", type=int, default=2)
    cloud.add_argument("--seed", type=int, default=0)
    cloud.add_argument("--concurrency", type=int, default=1, help="maximum simultaneous sandbox/browser pairs")
    cloud.add_argument("--output", type=Path, default=Path("runs/solari-latest.json"))
    for mode in ("replay", "minimize", "compare"):
        command = sub.add_parser(mode, help=f"{mode} a saved future")
        command.add_argument("future", type=Path)
    regression = sub.add_parser("regress", help="run checked-in regression futures")
    regression.add_argument("--directory", type=Path, default=Path("regressions"))
    args = parser.parse_args()
    if args.mode in {"run", "local"}:
        local_run(args.futures, args.seed, args.output)
    elif args.mode == "solari":
        asyncio.run(solari_run(args.futures, args.seed, args.output, args.concurrency))
    elif args.mode == "regress":
        raise SystemExit(regress(args.directory))
    else:
        raise SystemExit(saved_future_command(args.mode, args.future))


if __name__ == "__main__":
    main()
