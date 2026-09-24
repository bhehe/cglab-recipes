# cglab — CGF / DGX-Spark sparkrun recipe registry

A sparkrun **recipe registry** we own. It is a git repo with the standard
sparkrun registry shape (`.sparkrun/registry.yaml` + `recipes/`), so sparkrun
can register it and resolve `@cglab/...` references on any node — exactly like
the `atlas`, `eugr`, and `community` registries.

The point: custom recipes the public registries do not carry become
**first-class, distributable references**. Any node, profile, or worker can
`sparkrun run @cglab/qwen3.8-27b-nvfp4-pool` without copying a file around.

## Register it (one time, per host)

```bash
sparkrun registry add https://github.com/bhehe/cglab-recipes
# or, trusted (recipe hooks auto-run without prompting):
sparkrun registry add --trust https://github.com/bhehe/cglab-recipes
```

This clones the repo, reads `.sparkrun/registry.yaml`, and adds the `cglab`
registry to `~/.config/sparkrun/registries.yaml`.

## Use it

```bash
sparkrun list                                   # cglab recipes appear here
sparkrun show @cglab/qwen3.8-27b-nvfp4-pool     # detail + VRAM estimate
sparkrun run  @cglab/qwen3.8-27b-nvfp4-pool --solo --hosts localhost --no-follow
sparkrun update                                 # refresh cglab (and all) registries
```

House lifecycle (preferred on the pool): `mystack serve-switch <node>
--recipe '@cglab/qwen3.8-27b-nvfp4-pool'` — engine on :8000, LiteLLM proxy on
:4000, 4-gate verification.

## Layout

```
.sparkrun/registry.yaml            # the sparkrun registry manifest (name cglab, recipes: recipes)
recipes/
  qwen3.8-27b-nvfp4-pool.yaml      # the pool profile (thinking ON + batch 8 + 64k fp8 KV)
findings/
  qwen3.8-pool-findings.md         # measured findings shipped with the recipe
validate.py                        # CI check: every recipe parses + container ref resolves
.github/workflows/validate.yml     # runs validate.py on every push/PR
```

### Qualified names
A recipe's user-typeable name is `@cglab/<path-under-recipes, no extension>`.
Flat layout today → `@cglab/qwen3.8-27b-nvfp4-pool`. Add future variants as new
files (optionally in subdirs); sparkrun resolves both flat and nested
(`@cglab/qwen3.8/...`) by path.

## How to add a recipe

1. Drop the `.yaml` into `recipes/` (copy a stock atlas recipe, change the
   operating point). Required top-level keys: `recipe_version`, `model`,
   `runtime`, `container`, plus a `defaults:` block.
2. `sparkrun recipe validate recipes/<name>.yaml` — must be clean (suggestions
   are non-blocking; errors are not).
3. Ship the measured evidence in `findings/` and link it from the recipe's
   `metadata` (see the pool recipe). Keep the recipe self-documenting.
4. Commit + push. `validate.py` runs in CI; `sparkrun update` picks it up.

## How to roll back

- **Revert a bad recipe:** `git revert <commit>` and push — the next
  `sparkrun update` restores the prior file. sparkrun does `reset --hard
  FETCH_HEAD`, so deleted files are removed too.
- **Remove the whole registry:** `sparkrun registry remove cglab` (per host).

## CI / verify

`validate.py` ensures a bad recipe never reaches a node: every recipe parses
against the sparkrun schema (it shells to `sparkrun recipe validate` when
available, else does a structural parse) and every `container:` image reference
resolves (Docker Hub tags are checked live; other registries are format-checked).
Wired to GitHub Actions (`.github/workflows/validate.yml`) on push/PR.

## Provenance

Recipes here are curated from the CGF repo (private) — the source of truth for
full context, raw benchmark data, and the design doc. The registry carries a
**public, self-sufficient** copy (recipe + measured findings) so nodes can pull
it anonymously. Cross-references in each recipe's `metadata` point back to the
CGF paths.
