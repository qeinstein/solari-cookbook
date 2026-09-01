"""Solari sandbox/browser execution for coverage-guided temporal futures."""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
from time import perf_counter

from .core import (
    INVARIANT_ID,
    event_sort_key,
    execute,
    future_fingerprint,
    invariant_holds,
    invariant_violations,
    observed_invariant_holds,
    observed_violation,
    observed_violations,
)
from .evidence import counterfactual_proof
from .runner import build_summary
from .search import SearchFuture, coverage_guided_search, find_failure_boundaries


ROOT = Path(__file__).parents[1]
EVENT_ACTIONS = {
    "customer_payment": "pay",
    "payment_webhook": "webhook",
    "dispute_opened": "dispute",
    "dispute_webhook": "dispute-webhook",
}


async def goto_preview(page, preview_url: str):
    for attempt in range(8):
        try:
            await page.goto(preview_url)
            return
        except Exception:
            if attempt == 7:
                raise
            await asyncio.sleep(0.5)


async def click_world_action(page, selector: str, action: str):
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


def timestamp_observed_trace(trace, events, fixed=False):
    agent_action = f"agent/{'fixed' if fixed else 'original'}"
    expected = [
        (event, agent_action if event.kind == "agent_wakeup" else EVENT_ACTIONS[event.kind])
        for event in sorted(events, key=event_sort_key)
        if event.kind != "invoice_created"
    ]
    if len(trace) != len(expected):
        raise RuntimeError(f"observed {len(trace)} actions for {len(expected)} temporal events")
    timestamped = []
    required_state = {
        "payment",
        "crm",
        "dispute",
        "crm_dispute",
        "webhook_scheduled",
        "dispute_webhook_scheduled",
    }
    for raw_item, (event, expected_action) in zip(trace, expected):
        item = dict(raw_item)
        if item.get("action") != expected_action:
            raise RuntimeError(
                f"observed action {item.get('action')} where {expected_action} was expected"
            )
        missing = sorted(required_state - item.keys())
        if missing:
            raise RuntimeError(
                f"observed {expected_action} action is missing state evidence: {', '.join(missing)}"
            )
        item["at"] = event.at.isoformat()
        timestamped.append(item)
    return timestamped


def browser_simulator_parity(observed, trace, events, fixed=False):
    simulated = execute(events, fixed=fixed)
    ordered_events = [
        event for event in sorted(events, key=event_sort_key)
        if event.kind != "invoice_created"
    ]
    if len(trace) != len(ordered_events):
        raise RuntimeError(
            f"observed {len(trace)} trace states for {len(ordered_events)} temporal events"
        )
    previous_message_count = 0
    for index, (item, event) in enumerate(zip(trace, ordered_events)):
        prefix = execute(
            [
                candidate
                for candidate in sorted(events, key=event_sort_key)
                if candidate.kind != "invoice_created"
            ][: index + 1],
            fixed=fixed,
        )
        browser_step_state = (
            item["payment"],
            item["crm"],
            item["dispute"],
            item["crm_dispute"],
        )
        simulator_step_state = (
            prefix.payment_status,
            prefix.invoice_status,
            prefix.dispute_status,
            prefix.crm_dispute_status,
        )
        if browser_step_state != simulator_step_state:
            raise RuntimeError(
                f"browser/simulator trace mismatch after {event.kind}: "
                f"{browser_step_state} != {simulator_step_state}"
            )
        expected_payment_schedule = any(
            candidate.kind == "customer_payment"
            for candidate in ordered_events[: index + 1]
        )
        expected_dispute_schedule = any(
            candidate.kind == "dispute_opened"
            for candidate in ordered_events[: index + 1]
        )
        if item["webhook_scheduled"] != expected_payment_schedule:
            raise RuntimeError(f"payment scheduling mismatch after {event.kind}")
        if item["dispute_webhook_scheduled"] != expected_dispute_schedule:
            raise RuntimeError(f"dispute scheduling mismatch after {event.kind}")
        if event.kind == "agent_wakeup":
            actual_sent = bool(item.get("sent"))
            expected_sent = len(prefix.messages) > previous_message_count
            if actual_sent != expected_sent:
                raise RuntimeError(f"agent send mismatch after {event.kind}")
        previous_message_count = len(prefix.messages)
    browser_state = (
        observed["payment"].lower(),
        observed["crm"].lower(),
        observed["dispute"].lower(),
        observed["crm_dispute"].lower(),
    )
    simulator_state = (
        simulated.payment_status,
        simulated.invoice_status,
        simulated.dispute_status,
        simulated.crm_dispute_status,
    )
    browser_message_count = observed.get("message_count")
    if browser_message_count is None:
        browser_message_count = 0 if observed["messages"] == "No messages sent." else len(observed["messages"].splitlines())
    simulator_modes = sorted({item["type"] for item in invariant_violations(simulated)})
    observed_modes = sorted({item["type"] for item in observed_violations(trace)})
    if browser_state != simulator_state:
        raise RuntimeError(f"browser/simulator state mismatch: {browser_state} != {simulator_state}")
    if browser_message_count != len(simulated.messages):
        raise RuntimeError(
            f"browser/simulator message mismatch: {browser_message_count} != {len(simulated.messages)}"
        )
    if observed_modes != simulator_modes:
        raise RuntimeError(f"browser/simulator violation mismatch: {observed_modes} != {simulator_modes}")
    if observed_invariant_holds(trace) != invariant_holds(simulated):
        raise RuntimeError("browser/simulator invariant result mismatch")
    return {
        "verified": True,
        "trace_state_match": True,
        "state_match": True,
        "message_count_match": True,
        "violation_match": True,
        "simulator_failure_modes": simulator_modes,
    }


async def solari_future(
    future: SearchFuture,
    fixed: bool = False,
    recording_dir: Path | None = None,
):
    from solari_browser import Solari
    from solari_browser.errors import SolariError
    from solari_sandbox import SandboxClient

    sandbox_client = SandboxClient(
        api_key=os.environ["SOLARI_API_KEY"],
        base_url="https://api.getsolari.com",
    )
    async with sandbox_client:
        sandbox = await sandbox_client.create(template="base", timeout_ms=10 * 60_000)
        try:
            await sandbox.connect()
            remote_root = "/tmp/timecapsule-world"
            await sandbox.commands.run("mkdir", args=["-p", remote_root])
            await sandbox.files.write(
                f"{remote_root}/server.py",
                (ROOT / "world/server.py").read_text(),
            )
            await sandbox.files.write(
                f"{remote_root}/index.html",
                (ROOT / "world/index.html").read_text(),
            )
            await sandbox.commands.run(
                "sh",
                args=["-c", f"cd {remote_root} && nohup python3 server.py >/tmp/timecapsule.log 2>&1 &"],
            )
            preview_url = (await sandbox.preview_url(8765))["url"]

            async with Solari(api_key=os.environ["SOLARI_API_KEY"]) as solari:
                browser_session_id = None
                result = None
                async with await solari.launch(recording=True) as browser:
                    browser_session_id = browser.id
                    page = await browser.new_page()
                    await goto_preview(page, preview_url)
                    await click_world_action(page, 'button[data-action="reset"]', "reset")
                    for event in future.events:
                        if event.kind == "invoice_created":
                            continue
                        action = (
                            f"agent/{'fixed' if fixed else 'original'}"
                            if event.kind == "agent_wakeup"
                            else EVENT_ACTIONS[event.kind]
                        )
                        await click_world_action(
                            page,
                            f'button[data-action="{action}"]',
                            action,
                        )
                    observed = {
                        "payment": await page.locator("#payment").inner_text(),
                        "crm": await page.locator("#crm").inner_text(),
                        "dispute": await page.locator("#dispute").inner_text(),
                        "crm_dispute": await page.locator("#crm-dispute").inner_text(),
                        "messages": await page.locator("#messages").inner_text(),
                        "message_count": int(await page.locator("#messages").get_attribute("data-message-count") or "-1"),
                    }
                    trace = timestamp_observed_trace(
                        await read_world_trace(page),
                        future.events,
                        fixed=fixed,
                    )
                    observed["trace"] = trace
                    parity = browser_simulator_parity(observed, trace, future.events, fixed=fixed)
                    violations = observed_violations(trace)
                    result = {
                        "future_id": future.future_id,
                        "seed": future.seed,
                        "status": "PASS" if observed_invariant_holds(trace) else "FAIL",
                        "agent": "fixed" if fixed else "original",
                        "invariant": INVARIANT_ID,
                        "sandbox_id": sandbox.sandboxId,
                        "browser_session_id": browser_session_id,
                        "preview_url": preview_url,
                        "input_hash": future_fingerprint(future.events),
                        "violation": observed_violation(trace),
                        "violations": violations,
                        "failure_modes": sorted({item["type"] for item in violations}),
                        "boundaries": find_failure_boundaries(future.events),
                        "counterfactual_proof": counterfactual_proof(future.events),
                        "events": [event.as_dict() for event in future.events],
                        "search": {
                            "parent_future_id": future.parent_future_id,
                            "mutation": future.mutation,
                            "novel_features": sorted(future.novel_features),
                            "shared_prefix_events": future.shared_prefix_events,
                        },
                        "observed": observed,
                        "recording_keyframes": trace,
                        "browser_simulator_parity": parity,
                    }
                    await asyncio.sleep(2)
                if recording_dir and browser_session_id:
                    recording_dir.mkdir(parents=True, exist_ok=True)
                    suffix = "fixed" if fixed else "original"
                    recording_path = recording_dir / f"{future.future_id}-{suffix}.ndjson"
                    for _ in range(10):
                        try:
                            replay = await solari.sessions.download_replay(browser_session_id)
                            recording_path.write_bytes(replay)
                            result.update({
                                "recording_status": "downloaded",
                                "recording_path": str(recording_path),
                                "recording_bytes": len(replay),
                                "recording_events": len(replay.decode().splitlines()),
                            })
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


async def solari_run(
    count: int,
    seed_start: int,
    output: Path,
    concurrency: int = 1,
):
    if not os.environ.get("SOLARI_API_KEY"):
        raise SystemExit("SOLARI_API_KEY is required for Solari mode")
    if concurrency < 1:
        raise SystemExit("--concurrency must be at least 1")
    started = perf_counter()
    search = coverage_guided_search(count, seed_start)
    recording_dir = output.parent / "replays"
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded_future(future, fixed=False):
        async with semaphore:
            return await solari_future(future, fixed=fixed, recording_dir=recording_dir)

    results = await asyncio.gather(*(bounded_future(future) for future in search.futures))
    failing = [
        (future, result)
        for future, result in zip(search.futures, results)
        if result["status"] == "FAIL"
    ]
    patched = await asyncio.gather(*(bounded_future(future, fixed=True) for future, _ in failing))
    patched_by_id = {result["future_id"]: result for result in patched}
    for result in results:
        candidate = patched_by_id.get(result["future_id"])
        if candidate and candidate["input_hash"] != result["input_hash"]:
            raise RuntimeError(f"counterfactual input mismatch for {result['future_id']}")
        result["comparison"] = {
            "original": result["status"],
            "patched": candidate["status"] if candidate else "NOT_RUN",
        }
        if candidate:
            result["counterfactual_proof"]["runtime"] = {
                "same_event_hash": candidate["input_hash"] == result["input_hash"],
                "same_environment_hash": candidate["counterfactual_proof"]["original"]["environment_hash"] == result["counterfactual_proof"]["original"]["environment_hash"],
                "fresh_isolation": (
                    candidate["sandbox_id"] != result["sandbox_id"]
                    and candidate["browser_session_id"] != result["browser_session_id"]
                ),
                "original_sandbox_id": result["sandbox_id"],
                "patched_sandbox_id": candidate["sandbox_id"],
                "original_browser_session_id": result["browser_session_id"],
                "patched_browser_session_id": candidate["browser_session_id"],
            }
            result["patched_run"] = {
                key: candidate[key]
                for key in (
                    "agent",
                    "status",
                    "input_hash",
                    "sandbox_id",
                    "browser_session_id",
                    "recording_path",
                    "recording_bytes",
                    "recording_events",
                    "recording_status",
                    "recording_keyframes",
                    "observed",
                    "browser_simulator_parity",
                )
                if key in candidate
            }
    elapsed = perf_counter() - started
    summary = build_summary(
        results,
        [future.events for future in search.futures],
        search,
        elapsed,
        environments_used=len(results) + len(patched),
    )
    summary["recordings_downloaded"] = sum(
        result.get("recording_status") == "downloaded" for result in results + patched
    )
    payload = {
        "run_id": f"solari-{seed_start}-{seed_start + count - 1}",
        "execution_mode": "solari",
        "started_at": datetime.now().astimezone().isoformat(),
        "futures": results,
        "summary": summary,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print("Solari exploration")
    print(f"Isolated futures: {len(results)} (max concurrency {concurrency})")
    print(f"Failures found: {len(failing)} {summary['failure_modes']}")
    print(f"Patched replays: {len(patched)}")
    print(f"Environments used: {summary['environments_used']}")
    print(f"Wall clock: {summary['wall_clock_seconds']:.4f}s")
    print(f"Run saved: {output}")
    for result in results:
        print(
            f"{result['future_id']}: original={result['comparison']['original']} "
            f"patched={result['comparison']['patched']}"
        )
    return payload
