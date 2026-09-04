#!/usr/bin/env python3
"""Terminal viewer for the runtime agentic loop (Plan -> Act -> Observe -> Adapt).

The chat features in `almanac/`, `vgarden/` and `health/` log every phase of every
answer to `tools/ai-loop/logs/<service>.jsonl` (+ a markdown transcript per run).
This replays them and can check that each run follows the four-phase workflow.

    python tools/ai-loop/view.py                 # recent runs, all services
    python tools/ai-loop/view.py <run_id>        # full trace of one run
    python tools/ai-loop/view.py check           # validate every run vs the workflow
    python tools/ai-loop/view.py --service vgarden --last 20
    python tools/ai-loop/view.py --follow        # live tail, pretty-printed

No dependencies. See docs/agentic-ai-workflow.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import OrderedDict
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
SERVICES = ("almanac", "vgarden", "health")

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
GREEN, RED, YELLOW = "\033[32m", "\033[31m", "\033[33m"
PHASE_COLOR = {
    "plan": "\033[36m",      # cyan
    "act": "\033[33m",       # yellow
    "observe": "\033[35m",   # magenta
    "adapt": "\033[32m",     # green
    "fallback": "\033[31m",  # red
}


def _events(service: str) -> list[dict]:
    path = LOG_DIR / f"{service}.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _all_events(service: str | None) -> list[dict]:
    services = [service] if service else SERVICES
    events: list[dict] = []
    for name in services:
        events.extend(_events(name))
    events.sort(key=lambda e: e.get("ts", ""))
    return events


def _runs(service: str | None) -> "OrderedDict[str, list[dict]]":
    runs: OrderedDict[str, list[dict]] = OrderedDict()
    for event in _all_events(service):
        runs.setdefault(event["run_id"], []).append(event)
    return runs


def _c(phase: str, text: str) -> str:
    return f"{PHASE_COLOR.get(phase, '')}{text}{RESET}"


def _verdict(events: list[dict]) -> str:
    tail = [e for e in events if e["phase"] in ("adapt", "fallback")]
    if not tail:
        return "?"
    return tail[-1].get("decision") or tail[-1].get("reason", "fallback")


def cmd_list(service: str | None, last: int) -> int:
    runs = _runs(service)
    if not runs:
        print(f"No loop runs logged yet under {LOG_DIR}/")
        print(f"{DIM}(runs appear here once the AI chat is used, or after a seeded `docker compose up`){RESET}")
        return 0
    rows = list(runs.items())[-last:]
    print(f"{BOLD}{'run_id':<34}{'phases':<22}{'result':<16}iters{RESET}")
    for run_id, events in rows:
        phases = [e["phase"] for e in events]
        iters = max((e.get("iteration", 0) for e in events), default=0) or 1
        plain = " ".join(p[0].upper() for p in phases)
        seq = " ".join(_c(p, p[0].upper()) for p in phases)
        print(f"{run_id:<34}{seq}{' ' * max(1, 22 - len(plain))}{_verdict(events):<16}{iters}")
    print(f"\n{DIM}one run:   python tools/ai-loop/view.py <run_id>{RESET}")
    print(f"{DIM}validate:  python tools/ai-loop/view.py check{RESET}")
    return 0


def cmd_show(run_id: str) -> int:
    events = _runs(None).get(run_id)
    if not events:
        print(f"Unknown run_id: {run_id}")
        return 1

    service = events[0]["service"]
    question = next((e.get("question") for e in events if e.get("question")), "")
    print(f"{BOLD}{run_id}{RESET}  {DIM}({service}){RESET}")
    print(f"{BOLD}Q:{RESET} {question}\n")
    print(f"{DIM}Workflow: Plan -> Act -> Observe -> Adapt{RESET}\n")

    for event in events:
        phase = event["phase"]
        head = phase.upper()
        if event.get("iteration"):
            head += f" #{event['iteration']}"
        print(f"{_c(phase, BOLD + head + RESET)}  {DIM}+{event.get('elapsed_ms', 0)} ms{RESET}")
        for key, value in event.items():
            if key in ("phase", "iteration", "elapsed_ms", "ts", "run_id", "service", "question"):
                continue
            text = str(value)
            if "\n" in text:
                text = "\n    " + text.replace("\n", "\n    ")
            print(f"  {DIM}{key}:{RESET} {text}")
        print()

    transcript = LOG_DIR / "reports" / service / f"{run_id}.md"
    if transcript.is_file():
        print(f"{DIM}transcript: {transcript}{RESET}")
    return 0


def _check_run(run_id: str, events: list[dict]) -> list[str]:
    """Return a list of problems; empty means the run follows the workflow."""
    problems: list[str] = []
    phases = [e["phase"] for e in events]

    if not phases or phases[0] != "plan":
        problems.append("does not start with PLAN")

    if phases == ["plan", "fallback"]:
        return problems  # a clean single-shot fallback is allowed

    # After PLAN, expect one or more (act, observe, adapt) triples.
    body = phases[1:]
    if len(body) % 3 != 0 or set(body[0::3]) - {"act"} or set(body[1::3]) - {"observe"} \
            or set(body[2::3]) - {"adapt"}:
        problems.append(f"phase sequence is not plan + (act,observe,adapt)*: {phases}")

    acts = [e for e in events if e["phase"] == "act"]
    observes = [e for e in events if e["phase"] == "observe"]
    adapts = [e for e in events if e["phase"] == "adapt"]

    for ev in observes:
        if ev.get("verdict") not in ("approved", "revise"):
            problems.append(f"OBSERVE #{ev.get('iteration')} has no verdict")

    # On a 'revise', the following ACT must carry the reviewer's feedback.
    for i, ev in enumerate(adapts):
        if ev.get("decision") == "revise":
            nxt = next((a for a in acts if a.get("iteration") == ev.get("iteration", 0) + 1), None)
            if nxt is None:
                problems.append(f"ADAPT #{ev.get('iteration')} said 'revise' but no next ACT")
            elif not nxt.get("carried_feedback") or nxt["carried_feedback"] == "(none)":
                problems.append(
                    f"ACT #{nxt.get('iteration')} did not carry the reviewer's feedback"
                )

    terminal = _verdict(events)
    if terminal not in ("accept", "stop_capped", "fallback",
                        "no review model configured", "reviewer unreachable"):
        problems.append(f"unexpected terminal state: {terminal}")

    return problems


def cmd_check(service: str | None) -> int:
    runs = _runs(service)
    if not runs:
        print("No loop runs to check yet.")
        return 0

    ok = bad = 0
    print(f"{BOLD}Checking every run against Plan -> Act -> Observe -> Adapt{RESET}\n")
    for run_id, events in runs.items():
        problems = _check_run(run_id, events)
        iters = max((e.get("iteration", 0) for e in events), default=0) or 1
        if problems:
            bad += 1
            print(f"  {RED}FAIL{RESET}  {run_id}  ({iters} iter)")
            for p in problems:
                print(f"        {RED}- {p}{RESET}")
        else:
            ok += 1
            revised = any(e.get("decision") == "revise" for e in events)
            note = f"{YELLOW}revised then approved{RESET}" if revised else "approved"
            if _verdict(events) == "fallback":
                note = f"{DIM}single-shot fallback{RESET}"
            print(f"  {GREEN}PASS{RESET}  {run_id}  ({iters} iter, {note})")

    print(f"\n{BOLD}{ok} passed, {bad} failed{RESET}")
    print(f"{DIM}A run passes when: it starts with PLAN, alternates ACT/OBSERVE/ADAPT,{RESET}")
    print(f"{DIM}every OBSERVE has a verdict, and a 'revise' verdict is carried into the next ACT.{RESET}")
    return 1 if bad else 0


def cmd_follow(service: str | None) -> int:
    paths = {name: LOG_DIR / f"{name}.jsonl" for name in ([service] if service else SERVICES)}
    sizes = {name: (p.stat().st_size if p.is_file() else 0) for name, p in paths.items()}
    print(f"{DIM}following {', '.join(str(p) for p in paths.values())}  (Ctrl-C to stop){RESET}")
    try:
        while True:
            for name, path in paths.items():
                if not path.is_file():
                    continue
                size = path.stat().st_size
                if size < sizes[name]:
                    sizes[name] = 0
                if size > sizes[name]:
                    with path.open("r", encoding="utf-8") as fh:
                        fh.seek(sizes[name])
                        for line in fh:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                event = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            head = event["phase"].upper()
                            if event.get("iteration"):
                                head += f" #{event['iteration']}"
                            extra = " ".join(
                                f"{k}={v}"
                                for k, v in event.items()
                                if k in ("verdict", "decision", "reason", "draft_chars")
                            )
                            print(
                                f"{DIM}{event['ts'][11:19]}{RESET} "
                                f"{event['service']:<8} {_c(event['phase'], head):<22} {extra}"
                            )
                    sizes[name] = size
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("run_id", nargs="?", help="a run_id to show, or 'check' to validate all runs")
    parser.add_argument("--service", choices=SERVICES, help="limit to one service")
    parser.add_argument("--last", type=int, default=15, help="how many recent runs to list")
    parser.add_argument("--follow", action="store_true", help="live tail the logs")
    args = parser.parse_args()

    if args.follow:
        return cmd_follow(args.service)
    if args.run_id == "check":
        return cmd_check(args.service)
    if args.run_id:
        return cmd_show(args.run_id)
    return cmd_list(args.service, args.last)


if __name__ == "__main__":
    sys.exit(main())
