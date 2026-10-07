# qwen3.8-27b-fp8-dflash2-vllm — measured findings

**Recipe:** `@cglab/qwen3.8-27b-fp8-dflash2-vllm` (vLLM, DFlash2 draft-model speculative decode, K=7)
**Model:** Qwen/Qwen3.8-27B-FP8 · **Quantization:** FP8 · **Engine:** vllm 0.30.1 (dgx-vllm-eugr-nightly:latest, dflash.py PR #52816)
**Node:** spark-a010 (solo GB10, 121 GiB unified) · **Date:** 2026-10-07 · **Mode:** synthetic agentic (F-series battery)

## Operating point (this recipe)

- `speculative_config.method=dflash`, `draft_model=z-lab/Qwen3.8-27B-DFlash2`, `num_speculative_tokens=7` (K=7; community default, not K=4)
- `enable_thinking=True`, `max_model_len=262144` (256K), `gpu_memory_utilization=0.8`, `kv_cache_dtype=fp8_e4m3`,
  `attention_config.backend=flashinfer`, `enable_prefix_caching=True`
- **Engine port: 8000** (never 4000 — the proxy owns 4000)

## Result vs the house MTP K=4 baseline (same node, same battery, single-variable diff)

| Phase | MTP4 gen tok/s | DFlash2 gen tok/s | ratio |
|---|---|---|---|
| **C1** | 107.82 | **179.52** | **1.66x** |
| **C2** | 112.41 | **167.93** | **1.49x** |
| **C3** | 107.13 | 104.89 | 0.98x (par) |
| **C1-CTL (steady-state C1)** | 107.76 | **208.94** | **1.94x** |

- **ADOPT for C1-C2 agentic serving** (the regime our pool runs: thinking ON, C1-C2 per node).
  Decision threshold was 1.3x on C1/C2 gen with no reliability regression — cleared at 1.66x / 1.49x.
- **C3 = par (0.98x):** DFlash2 does not win at 3-stream concurrency; keep MTP K=4 for C3.
  This matches the community S5 finding that DFlash2 "wins C1-C2, loses at higher C".
- **Reliability:** 0 API errors, 0 crashes, 0 OOM across both legs, all 4 phases. One C3/T6
  degenerate max-tokens turn on the first run (clean isolated re-check) — a model-behavior note,
  not an engine fault; did not change the C3 (par) verdict.

## Spec-decode counters (cumulative, engine boot → battery end)

| | MTP4 | DFlash2 |
|---|---|---|
| decode steps | 5,923 | 4,818 |
| draft tokens | 23,692 | 33,726 |
| accepted tokens | 21,322 (3.60/step) | 9,988 (2.07/step) |
| per-position acceptance | 90% (K=4) | 64/55/39/28/19% (K=7) |

**Cost-per-accepted-token nuance:** DFlash2's raw tok/step (2.60) is lower than MTP4 (4.58), but that
is the *EAGLE uniform-step-cost proxy*. DFlash's step = one cheap 1.9B block-parallel drafter forward +
one target verify, vs MTP's 4 sequential target-head forwards. The fair metric (target-FLOPs per
accepted token) favors DFlash2 (≈0.33 vs ≈0.44), and the **measured throughput is decisive
(1.66x/1.49x/1.94x)**. Do not read the 2.07 accepted tok/step as a DFlash2 failure — it is a
cheaper-step method.

## KV / memory

- 256K served on a solo GB10 at util 0.8; boot clean, no OOM. K=7 drafter adds the 1.9B draft model to
  unified memory — fits comfortably (free mem 116-117 GiB throughout the battery).
- 512K is NOT served (model `max_position_embeddings=262144` caps it; multi-node only).

## Provenance

- Battery: `c3xnode_battery_a010.py` (F-series, 6 tasks, C1/C2/C3/C1-CTL, max_turns 8, 1500 max_tokens,
  thinking ON).
- State: `exp4-dflash2-a010/state_all_20261007_071052.json` (DFlash2), `state_all_20261007_080652.json` (MTP4).
- Full record: `exp4-dflash2-a010/EXP4-DFLASH2-A010-2026-10-07.json` · Findings: `exp4-dflash2-a010/FINDINGS.md`
- Baseline drift: MTP4 re-run C1 107.82 vs prior 108.11 (-0.3%, within noise) — A/B on a stable base.

## Cross-references

- House serving lifecycle: `@cglab/qwen3.8-27b-nvfp4-pool` (the pool operating point), MTP K=4 baseline.
- Serving skill: `dgx-spark-sparkrun-serving` (engine :8000 / proxy :4000, gated serve-switch).
- Design doc: `Recipes/ModelServing/MODEL-SERVING-DESIGN.md`.
