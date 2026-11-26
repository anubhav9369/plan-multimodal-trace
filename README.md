# plan-multimodal-trace

A **multimodal trace** for an InspectablePlan — part of the trustworthy
agentic AI prototype for BRJP26100123 (Week 4: multimodal tracing, after
the plan health score).

## Why

A plan step is only *traced* when the run leaves evidence for it, and
evidence comes in different modalities: a text log line, a screenshot
(image), a voice-note transcript (audio), or a screen recording
(video). One modality is not enough proof for an irreversible step —
sending an email leaves a log line, but the screenshot of the sent
folder and the spoken read of the recipient list are what let a human
trust that the right thing went to the right people. This tool reads a
plan and a JSONL trace of evidence events, checks the trace is well
formed, and reports which steps are covered — and in how many
modalities.

## Use

```bash
python3 plan_multimodal_trace.py examples/plan.json examples/trace.jsonl
python3 plan_multimodal_trace.py examples/plan.json examples/trace.jsonl --json
python3 plan_multimodal_trace.py examples/plan.json examples/trace.jsonl --out timeline.md
python3 plan_multimodal_trace.py examples/plan.json examples/trace.jsonl \
    --check-refs --base-dir examples
```

Exit codes: `0` = FULLY TRACED, `1` = GAPS, `2` = INVALID,
`3` = usage error (bad JSON, missing file).

## Rules (trace v1.0.0)

- Every step needs evidence in at least one modality.
- An **irreversible step needs evidence in at least two modalities**.
- A trace event must name a step in the plan, a known modality
  (`text`, `image`, `audio`, `video`), and a valid ISO-8601 timestamp;
  timestamps must be non-decreasing.
- Referenced files are only checked with `--check-refs` (rooted at
  `--base-dir`); a missing file is a problem, not a silent gap.
- A modality is evidence, not a claim: an audio event carries its
  transcript (or a note saying what was said), an image event carries a
  caption saying what it shows. An event with no note is still an
  event, but the timeline shows it as uncaptioned.
- A bad timestamp sorts first in the timeline, so the problem is
  visible at the top instead of crashing the report.

## Examples

- `examples/trace.jsonl` — full coverage: every step has evidence, the
  irreversible send step (s4) has three modalities (text log, sent-mail
  screenshot, spoken recipient check) — **FULLY TRACED**; report in
  `examples/timeline.md`.
- `examples/trace-gaps.jsonl` — s3 has no evidence at all, and s4 has
  only the text log — **GAPS**; report in `examples/timeline-gaps.md`.
- `examples/trace-invalid.jsonl` — unknown step s9, unknown modality
  `hologram`, a timestamp that goes backwards, a bad timestamp —
  **INVALID** (4 problems listed).

## Tests

```bash
python3 -m unittest discover -s tests -v
```

11 stdlib tests, no dependencies.
