"""TimeCapsule runner: local proof plus a real Solari execution mode."""

import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import sys

from timecapsule.core import comparison, execute, generate_future, invariant_holds, minimize, save_future

ROOT = Path(__file__).parent


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
    for seed in range(seed_start, seed_start + count):
        events = generate_future(seed)
        world = execute(events)
        entry = {"future_id": f"future-{seed}", "seed": seed, "agent": "original",
                 "status": "PASS" if invariant_holds(world) else "FAIL",
                 "invariant": "no_contact_during_stale_payment_window",
                 "events": [event.as_dict() for event in events], **serializable_world(world)}
        futures.append(entry)
        if entry["status"] == "FAIL":
            failures.append((seed, events))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"run_id": f"local-{seed_start}-{seed_start + count - 1}",
                                  "started_at": datetime.now().astimezone().isoformat(),
                                  "futures": futures,
                                  "summary": {"explored": count, "failures": len(failures)}}, indent=2) + "\n")
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


async def solari_future(seed: int, fixed: bool = False):
    """Run one future in one isolated Solari sandbox + browser pair."""
    from solari_browser import Solari
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
                async with await solari.launch(recording=True) as browser:
                    page = await browser.new_page()
                    await page.goto(preview_url)
                    await page.locator('button[data-action="reset"]').click()
                    for event in generate_future(seed):
                        if event.kind == "customer_payment":
                            await page.locator('button[data-action="pay"]').click()
                        elif event.kind == "agent_wakeup":
                            action = "fixed" if fixed else "original"
                            await page.locator(f'button[data-action="agent/{action}"]').click()
                        elif event.kind == "payment_webhook":
                            await page.locator('button[data-action="webhook"]').click()
                    messages = await page.locator("#messages").inner_text()
                    payment = await page.locator("#payment").inner_text()
                    crm = await page.locator("#crm").inner_text()
                    failed = payment == "PAID" and crm == "OVERDUE" and messages != "No messages sent."
                    return {"future_id": f"future-{seed}", "seed": seed, "status": "FAIL" if failed else "PASS",
                            "agent": "fixed" if fixed else "original", "sandbox_id": sandbox.sandboxId,
                            "browser_session_id": browser.id, "preview_url": preview_url,
                            "events": [event.as_dict() for event in generate_future(seed)],
                            "observed": {"payment": payment, "crm": crm, "messages": messages}}
        finally:
            await sandbox.kill()


async def solari_run(count: int, seed_start: int, output: Path):
    if not os.environ.get("SOLARI_API_KEY"):
        raise SystemExit("SOLARI_API_KEY is required for Solari mode")
    results = await asyncio.gather(*(solari_future(seed) for seed in range(seed_start, seed_start + count)))
    failing_seeds = [result["seed"] for result in results if result["status"] == "FAIL"]
    patched = await asyncio.gather(*(solari_future(seed, fixed=True) for seed in failing_seeds))
    patched_by_seed = {result["seed"]: result for result in patched}
    for result in results:
        candidate = patched_by_seed.get(result["seed"])
        result["comparison"] = {"original": result["status"], "patched": candidate["status"] if candidate else "NOT_RUN"}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"run_id": f"solari-{seed_start}-{seed_start + count - 1}",
                                  "started_at": datetime.now().astimezone().isoformat(),
                                  "futures": results,
                                  "summary": {"explored": len(results), "failures": len(failing_seeds), "patched_replays": len(patched)}}, indent=2) + "\n")
    print("Solari exploration")
    print(f"Isolated futures: {len(results)} (sandbox + browser per future, run concurrently)")
    print(f"Failures found: {len(failing_seeds)}")
    print(f"Patched replays: {len(patched)}")
    print(f"Run saved: {output}")
    for result in results:
        print(f"{result['future_id']}: original={result['comparison']['original']} patched={result['comparison']['patched']} · sandbox {result['sandbox_id']} · browser {result['browser_session_id']}")


def main():
    parser = argparse.ArgumentParser(description="Explore collections-agent futures")
    sub = parser.add_subparsers(dest="mode", required=True)
    local = sub.add_parser("local", help="run the deterministic local engine")
    local.add_argument("--futures", type=int, default=25)
    local.add_argument("--seed", type=int, default=0)
    local.add_argument("--output", type=Path, default=Path("runs/latest.json"))
    cloud = sub.add_parser("solari", help="run isolated futures in Solari")
    cloud.add_argument("--futures", type=int, default=2)
    cloud.add_argument("--seed", type=int, default=0)
    cloud.add_argument("--output", type=Path, default=Path("runs/solari-latest.json"))
    args = parser.parse_args()
    if args.mode == "local":
        local_run(args.futures, args.seed, args.output)
    else:
        asyncio.run(solari_run(args.futures, args.seed, args.output))


if __name__ == "__main__":
    main()
