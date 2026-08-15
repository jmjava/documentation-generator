# Scene-timing benchmark corpus

Standard scripts scored by ``docgen benchmark`` / ``scripts/benchmark-scenes.sh``.

Each case is a **fixed spec + Whisper-shaped word list** that encodes a
production failure we have already shipped by accident:

| id | What it proves |
| --- | --- |
| `issue66_tight_clamped` | Tight spoken labels + long authored `run_time` must **not** skip waits after compile clamp |
| `issue66_tight_unclamped` | **Control** — same spec compiled *without* words still dumps (scorer is not blind) |
| `early_title` | Title `Write` must shrink so a 0.55s first label is not skipped |
| `wide_hold` | Long subject-beat holds get more than one pulse |
| `emphasis_none` | Author opt-out stays still (no false “stuck” fail) |
| `paged_slide` | Slide page transition does not skip the next `wait_word` |
| `flow_edges` | Grow + edge-to-edge arrow still paces |
| `audio_tail` | Last box keeps moving through a long tail |

`baseline.json` is the last accepted scorecard. A change that raises
`defect_points` or drops `quality_points` fails the command (exit 1).

After an **intentional** improvement:

```bash
docgen benchmark --update-baseline
```

Review the baseline diff in Git. Do not bump it to hide a regression.
