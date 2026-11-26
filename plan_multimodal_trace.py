#!/usr/bin/env python3
"""Multimodal trace for an InspectablePlan.

A plan step is only *traced* when the run leaves evidence for it, and
evidence comes in different modalities: a text log line, a screenshot
(image), a voice-note transcript (audio), or a screen recording (video).
This tool reads a plan and a JSONL trace of evidence events, checks the
trace is well formed, and reports which steps are covered -- and in how
many modalities.

Trace rules v1.0.0:
- Every step needs evidence in at least one modality.
- An irreversible step needs evidence in at least two modalities: one
  modality is not enough proof for something that cannot be undone.
- A trace event must name a step in the plan, a known modality, and a
  valid ISO-8601 timestamp; timestamps must be non-decreasing.
- Referenced files are only checked when --check-refs is given, with
  --base-dir as the root; a missing file is a problem, not a silent gap.
- A modality is evidence, not a claim: an audio event carries its
  transcript (or a note saying what was said), an image event carries a
  caption saying what it shows. An event with no note is still an event,
  but the timeline shows it as uncaptioned.

Exit codes: 0 = FULLY TRACED, 1 = GAPS, 2 = INVALID, 3 = usage error.

Usage:
  python3 plan_multimodal_trace.py examples/plan.json examples/trace.jsonl
  python3 plan_multimodal_trace.py examples/plan.json examples/trace.jsonl --json
  python3 plan_multimodal_trace.py examples/plan.json examples/trace.jsonl --out timeline.md
  python3 plan_multimodal_trace.py examples/plan.json examples/trace.jsonl \
      --check-refs --base-dir examples
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

MODALITIES = ("text", "image", "audio", "video")
RULES_VERSION = "1.0.0"


def parse_ts(value):
    """Parse an ISO-8601 timestamp; return an aware datetime or None.

    A timestamp with no timezone is read as UTC, so naive and aware
    values never meet in a comparison.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def load_plan(path):
    with open(path, encoding="utf-8") as f:
        plan = json.load(f)
    if not isinstance(plan, dict) or "steps" not in plan:
        raise ValueError("plan must be a JSON object with a 'steps' list")
    return plan


def load_trace(path):
    events = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"trace line {lineno}: not valid JSON ({exc})")
            if not isinstance(event, dict):
                raise ValueError(f"trace line {lineno}: event must be an object")
            event["_lineno"] = lineno
            events.append(event)
    return events


def validate_trace(plan, events, base_dir=None, check_refs=False):
    """Return a list of problems; empty means the trace is well formed."""
    problems = []
    step_ids = {s["id"] for s in plan["steps"]}
    prev_ts = None
    for event in events:
        lineno = event.get("_lineno", "?")
        step = event.get("step_id")
        if step not in step_ids:
            problems.append(f"line {lineno}: unknown step_id {step!r}")
        modality = event.get("modality")
        if modality not in MODALITIES:
            problems.append(
                f"line {lineno}: unknown modality {modality!r} "
                f"(known: {', '.join(MODALITIES)})"
            )
        ts = parse_ts(event.get("ts"))
        if ts is None:
            problems.append(f"line {lineno}: bad timestamp {event.get('ts')!r}")
        elif prev_ts is not None and ts < prev_ts:
            problems.append(
                f"line {lineno}: timestamp {event.get('ts')} is before "
                f"the previous event -- trace must be chronological"
            )
        if ts is not None:
            prev_ts = ts
        if not event.get("kind"):
            problems.append(f"line {lineno}: missing 'kind'")
        if check_refs and base_dir and event.get("ref"):
            ref_path = os.path.join(base_dir, event["ref"])
            if not os.path.exists(ref_path):
                problems.append(
                    f"line {lineno}: referenced file missing: {event['ref']}"
                )
    return problems


def build_timeline(events):
    """Chronological timeline, sorted by timestamp (input order kept on ties)."""
    keyed = []
    for order, event in enumerate(events):
        # A bad timestamp sorts first, so the problem is visible at the
        # top of the timeline instead of crashing the sort.
        ts = parse_ts(event.get("ts")) or datetime.min.replace(tzinfo=timezone.utc)
        keyed.append((ts, order, event))
    keyed.sort(key=lambda item: (item[0], item[1]))
    return [event for _, _, event in keyed]


def coverage(plan, events):
    """Per-step modality coverage. Returns {step_id: {...}} in plan order."""
    by_step = {}
    for event in events:
        by_step.setdefault(event.get("step_id"), []).append(event)
    result = {}
    for step in plan["steps"]:
        step_id = step["id"]
        step_events = by_step.get(step_id, [])
        modalities = sorted({e["modality"] for e in step_events
                             if e.get("modality") in MODALITIES})
        reversible = step.get("reversible", True)
        required = 1 if reversible else 2
        if not modalities:
            gap = "no evidence in any modality"
        elif len(modalities) < required:
            gap = (f"irreversible step has evidence in only "
                   f"{len(modalities)} modalit{'y' if len(modalities) == 1 else 'ies'} "
                   f"({', '.join(modalities)}); needs {required}")
        else:
            gap = None
        result[step_id] = {
            "modalities": modalities,
            "events": len(step_events),
            "reversible": reversible,
            "required_modalities": required,
            "covered": gap is None,
            "gap": gap,
        }
    return result


def verdict(problems, cov):
    if problems:
        return "INVALID"
    if all(info["covered"] for info in cov.values()):
        return "FULLY TRACED"
    return "GAPS"


def report(plan, events, problems, cov):
    """Full report dict: verdict, problems, per-step coverage, timeline."""
    timeline = build_timeline(events)
    return {
        "plan": plan.get("id"),
        "plan_version": plan.get("version"),
        "plan_goal": plan.get("goal"),
        "rules_version": RULES_VERSION,
        "verdict": verdict(problems, cov),
        "problems": problems,
        "coverage": cov,
        "timeline": [
            {
                "ts": e.get("ts"),
                "step_id": e.get("step_id"),
                "modality": e.get("modality"),
                "kind": e.get("kind"),
                "ref": e.get("ref"),
                "note": e.get("note"),
            }
            for e in timeline
        ],
    }


def render_markdown(rep):
    lines = [
        f"# Multimodal trace — {rep['plan']} (v{rep['plan_version']})",
        "",
        f"Goal: {rep['plan_goal']}",
        f"Rules: trace v{rep['rules_version']}",
        "",
        f"## Verdict: {rep['verdict']}",
        "",
    ]
    if rep["problems"]:
        lines.append("### Problems")
        lines.append("")
        for problem in rep["problems"]:
            lines.append(f"- {problem}")
        lines.append("")
    lines.append("### Coverage")
    lines.append("")
    lines.append("| Step | Reversible | Modalities | Events | Covered |")
    lines.append("|---|---|---|---|---|")
    for step_id, info in rep["coverage"].items():
        modalities = ", ".join(info["modalities"]) or "—"
        covered = "yes" if info["covered"] else f"no — {info['gap']}"
        lines.append(
            f"| {step_id} | {'yes' if info['reversible'] else 'no'} | "
            f"{modalities} | {info['events']} | {covered} |"
        )
    lines.append("")
    lines.append("### Timeline")
    lines.append("")
    lines.append("| Time | Step | Modality | Kind | Ref | Note |")
    lines.append("|---|---|---|---|---|---|")
    for event in rep["timeline"]:
        note = event.get("note") or "— (uncaptioned)"
        lines.append(
            f"| {event.get('ts')} | {event.get('step_id')} | "
            f"{event.get('modality')} | {event.get('kind')} | "
            f"{event.get('ref') or '—'} | {note} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", help="InspectablePlan JSON file")
    parser.add_argument("trace", help="trace events, one JSON object per line")
    parser.add_argument("--base-dir", default=None,
                        help="root for --check-refs file lookups")
    parser.add_argument("--check-refs", action="store_true",
                        help="flag trace events whose ref file is missing")
    parser.add_argument("--json", action="store_true",
                        help="print the report as JSON instead of Markdown")
    parser.add_argument("--out", default=None,
                        help="write the report to this file instead of stdout")
    args = parser.parse_args(argv)

    try:
        plan = load_plan(args.plan)
        events = load_trace(args.trace)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    problems = validate_trace(plan, events, args.base_dir, args.check_refs)
    cov = coverage(plan, events)
    rep = report(plan, events, problems, cov)
    text = json.dumps(rep, indent=2) if args.json else render_markdown(rep)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)

    return {"FULLY TRACED": 0, "GAPS": 1, "INVALID": 2}[rep["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
