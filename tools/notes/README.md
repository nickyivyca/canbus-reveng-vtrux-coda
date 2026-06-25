# tools/notes/

Cross-tool investigations, benchmarks, and design write-ups that aren't
tied to a specific vehicle. Anything that would otherwise live in a
`projects/<vehicle>/notes/` folder but is really about how the **tools**
behave belongs here.

| Subfolder / file | What it covers |
|------------------|----------------|
| [influx_upload_benchmark.py](influx_upload_benchmark.py) | Single-file benchmark driver for `tools/influx_upload.py`. Uses one churny Vtrux Android T0 log; captures dry-run cProfile + real-upload cProfile + dumpcap pcap, then summarises the bottleneck. |
| [influx_upload_benchmark_series.py](influx_upload_benchmark_series.py) | Same idea, scaled to the full T0–T12 series (~535 MB / 13 files) so per-file scan-pass overhead is visible alongside steady-state streaming. |
| [influx_bench/](influx_bench/) | Single-log benchmark artifacts (`upload.pcapng`, `dry.prof`, `real.prof`, `analyze_pcap.py`, `findings.md`). |
| [influx_bench_series/](influx_bench_series/) | Series benchmark artifacts. `findings.md` is the pre-optimization baseline; `findings_after_optimizations.md` is the post-fast-scan/custom-serializer/DROP-fix re-run. |

## Conventions

- Benchmark drivers live next to their artifacts, not in `tools/` proper
  (they're investigative scratchpads, not user-facing CLI tools).
- All scripts are invoked from project root: `py -3.12 tools/notes/<script>.py`.
  Relative paths (e.g. `../../CANLogs/VtruxLogs/...`) resolve against the
  project root, matching the convention in `CLAUDE.md`.
- Vehicle-specific findings stay in `projects/<vehicle>/notes/` even when
  they were uncovered while benchmarking a tool. For example, the
  `android_churn_survey.csv` lives in `projects/vtrux/notes/artifacts/`
  because it's a per-Vtrux-log survey, not a tool benchmark.
