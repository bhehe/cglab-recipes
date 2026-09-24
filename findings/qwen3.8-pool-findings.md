# Measured findings — qwen3.8-27b-nvfp4-pool (the cglab pool recipe)

Durable, citable measurements backing `@cglab/qwen3.8-27b-nvfp4-pool`.
This file ships with the registry so the recipe is self-documenting on any node;
the full lab context (raw JSON, design doc, A/B board thread) lives in the CGF
repo (private) and is cross-referenced in the recipe metadata.

## What this recipe is

The **pool profile** for the 4-node DGX Spark (GB10) inference pool:
`thinking ON + batch 8 + 64k context + fp8 KV + MTP speculative decode` on
`nvidia/Qwen3.8-27B-NVFP4`. It is the operating point the stock atlas profiles
deliberately do not cover (see the recipe's `description` block).

## Measured numbers (the evidence base)

| Metric | Value | Source / date |
|---|---|---|
| Single-stream throughput (reference, stock agentic) | **~12.6–13.2 tok/s** (150-token window), 4 nodes within ±2.4% | 2026-09-18 pool benchmark, sparkrun toolchain: `tg` 12.67 tok/s (std 0.49), `pp` 437,809 tok/s prefill |
| Per-node concurrency (batch 1 era) | **Serialized** — wall time scales linearly with N; ideal per-node concurrency = **1x**, parallelism is cross-node | 2026-09-18 findings |
| Context-size effect | ~12.5k context ≈ **2.4× slower** than ~1.5k (9.81 → 4.13 tok/s @ C1) | 2026-09-18 smoke matrix |
| KV ceiling (fp8 KV, same weights) | **557,490 max tokens** (dry-run fit, 68.1 GB budget); **256K @ C1 BOOTS + SERVES** (51.89 GiB KV, 5.59× concurrency headroom); 512K = hard model cap (max_position_embeddings 262,144), not KV budget | 2026-09-21 f909 measured boot |
| Pool aggregate (4 nodes, 1 req each) | **~52 tok/s** at the 150-token window | 2026-09-18 |

**Interpretation for the pool recipe:** the pool's parallelism comes from
*batch 8 + routing across 4 nodes*, not stacking requests on one node. 64k
context is the honest working headroom (agents run 30k–150k; quality above ~24k
is uncharacterized on these weights — the bigger window buys truncation room,
not reasoning quality). KV is the memory binder at 121.7 GB; levers in order:
kv fp8 (set) → `gpu_memory_utilization` → `max_model_len` → `max_batch_size`.

## Boot/serving status of THIS recipe

- Recipe validates against the sparkrun schema (`sparkrun recipe validate`):
  clean (2 non-blocking metadata suggestions, no errors).
- Operating point (thinking ON + batch 8 + 64k @ 0.85 util) is the hypothesis
  the A/B benchmark settles (board task t_570ba14a); the certified stock
  `concurrency` profile (C1 23.59 → C128 478 tok/s, all 4 gates PASS) proves
  batch-8+ booting is sound on the same nvidia checkpoint.

## How to serve / verify

```bash
export PATH="$HOME/.local/bin:$PATH"
sparkrun update                      # refresh the registry
sparkrun show @cglab/qwen3.8-27b-nvfp4-pool
sparkrun run @cglab/qwen3.8-27b-nvfp4-pool --solo --hosts localhost --no-follow
sparkrun proxy start                  # LiteLLM proxy on :4000
```

House lifecycle (preferred): `mystack serve-switch <node> --recipe
'@cglab/qwen3.8-27b-nvfp4-pool'` — engine on :8000, proxy on :4000,
4-gate verification.

## CGF source of truth (private repo)

- Findings (full, with raw data): `Labs/PrimaryLab/benchmarks/Model-Serving-Performance-Findings.md`
- KV-MAX evidence: `Labs/KV-MAX/2026-09-21-kvmax-measured-f909.md`
- Design doc: `Recipes/ModelServing/MODEL-SERVING-DESIGN.md`
- Raw benchmark JSON: `Labs/PrimaryLab/benchmarks/inference-pool-2026-09-18.json`
