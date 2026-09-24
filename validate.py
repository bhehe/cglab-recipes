#!/usr/bin/env python3
"""cglab registry CI check — a bad recipe must never break `sparkrun run` on a node.

Checks, for every recipe under recipes/:
  1. YAML parses cleanly.
  2. Required top-level keys present (recipe_version, model, runtime, container).
  3. sparkrun schema — shells out to `sparkrun recipe validate <file>` when
     sparkrun is on PATH (authoritative); otherwise falls back to the
     structural checks below (still catches missing keys / bad port / no defaults).
  4. Container image reference resolves:
       - docker.io / bare (namespace/name:tag) -> Docker Hub tags API (live)
       - ghcr.io/<repo>:<tag>                  -> GHCR anonymous pull token + tags API
     (Use --no-network to skip the live image checks in offline dev.)

Exit: 0 = all recipes pass, 1 = one or more failures.
Usage: python3 validate.py [--no-network] [--sparkrun /path/to/sparkrun]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from pathlib import Path

ROOT = Path(__file__).resolve().parent
RECIPES = ROOT / "recipes"
REQUIRED_KEYS = ("recipe_version", "model", "runtime", "container")
DOCKER_HUB_RE = re.compile(r"^(?:(?:docker\.)?io/)?(?P<ns>[a-z0-9_.-]+)/(?P<name>[a-z0-9_.-]+?)(?::(?P<tag>[^:/]+))?$")
GHCR_RE = re.compile(r"^ghcr\.io/(?P<repo>[a-z0-9_.-]+/[a-z0-9_.-]+)(?::(?P<tag>[^:/]+))?$", re.I)


def http_get(url, headers=None, timeout=20, retries=2):
    headers = dict(headers or {})
    headers.setdefault("Accept", "application/json")
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception as e:  # URLError, timeout, ...
            last = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last


def check_image_dockerhub(ns, name, tag, quiet=False):
    """Resolve a Docker Hub image reference. tag defaults to 'latest'."""
    tag = tag or "latest"
    url = "https://hub.docker.com/v2/repositories/%s/%s/tags/%s" % (ns, name, urllib.request.quote(tag))
    status, body = http_get(url)
    ok = status == 200
    detail = ""
    if ok:
        try:
            d = json.loads(body)
            detail = "size=%s" % d.get("full_size")
        except Exception:
            pass
    elif status == 404:
        detail = "not found"
    else:
        detail = "HTTP %s" % status
    return ok, detail


def check_image_ghcr(repo, tag, quiet=False):
    """Resolve a GHCR image via the anonymous pull token endpoint."""
    tag = tag or "latest"
    tok_status, tok_body = http_get(
        "https://ghcr.io/token?scope=repository:%s:pull" % repo, timeout=15
    )
    if tok_status != 200:
        return False, "token endpoint HTTP %s" % tok_status
    try:
        token = json.loads(tok_body).get("token")
    except Exception:
        return False, "no token in response"
    if not token:
        return False, "empty token"
    url = "https://ghcr.io/v2/%s/tags/list" % repo
    status, body = http_get(url, headers={"Authorization": "Bearer " + token})
    if status == 200:
        try:
            tags = json.loads(body).get("tags") or []
        except Exception:
            tags = []
        return tag in tags, ("tag in %d published tags" % len(tags)) if tag in tags else "tag absent (have %d tags)" % len(tags)
    return False, "tags API HTTP %s" % status


def check_image_ref(ref):
    """Return (ok, how, detail) for a container image reference."""
    m = GHCR_RE.match(ref)
    if m:
        ok, detail = check_image_ghcr(m.group("repo"), m.group("tag"))
        return ok, "ghcr.io", detail
    m = DOCKER_HUB_RE.match(ref)
    if m:
        # Single-component references (e.g. 'busybox') are docker.io/library/*
        if "/" not in ref and "://" not in ref:
            ns, name = "library", ref.split(":")[0]
            tag = ref.split(":")[1] if ":" in ref else "latest"
        else:
            ns, name, tag = m.group("ns"), m.group("name"), m.group("tag")
        ok, detail = check_image_dockerhub(ns, name, tag)
        return ok, "docker.io/%s/%s" % (ns, name), detail
    return False, "unrecognized", "reference does not look like a pullable image ref"


def sparkrun_available(explicit=None):
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        w = shutil.which(explicit)
        if w:
            return w
        stem = os.path.splitext(os.path.basename(explicit))[0]
        w = shutil.which(stem)
        return w or None
    w = shutil.which("sparkrun")
    if w:
        return w
    # Windows: sparkrun.exe may be in ~/.local/bin but "sparkrun" lacks the .exe
    for cand in (os.path.join(os.path.expanduser("~"), ".local", "bin", "sparkrun.exe"),
                 os.path.join(os.path.expanduser("~"), ".local", "bin", "sparkrun")):
        if os.path.isfile(cand):
            return cand
    return None


def validate_recipe_file(path, sparkrun_bin):
    """Return list of (kind, message) where kind in {'error','suggestion','ok'}."""
    out = []
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None
    if yaml is None:
        out.append(("error", "PyYAML not available — cannot parse"))
        return out
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        out.append(("error", "YAML parse failed: %s" % e))
        return out
    if not isinstance(data, dict):
        out.append(("error", "top-level YAML is not a mapping"))
        return out
    for k in REQUIRED_KEYS:
        if not data.get(k):
            out.append(("error", "missing required key: %s" % k))
    if not data.get("defaults"):
        out.append(("error", "missing 'defaults' block"))
    port = (data.get("defaults") or {}).get("port")
    if port is not None and (isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535)):
        out.append(("error", "defaults.port must be an int 1-65535, got %r" % (port,)))
    if sparkrun_bin:
        try:
            r = subprocess.run(
                [sparkrun_bin, "recipe", "validate", str(path)],
                capture_output=True, text=True, timeout=120, cwd=ROOT,
            )
            if r.returncode == 0:
                out.append(("ok", "sparkrun recipe validate: PASS"))
                tail = (r.stdout or "").strip().splitlines()
                if tail:
                    out.append(("ok", tail[-1]))
            else:
                out.append(("error", "sparkrun recipe validate rc=%d: %s"
                            % (r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()[:400])))
        except Exception as e:
            out.append(("error", "sparkrun validate invocation failed: %s" % e))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-network", action="store_true", help="skip live container-image checks")
    ap.add_argument("--sparkrun", default=None, help="path to the sparkrun binary (default: $PATH)")
    args = ap.parse_args()

    if not RECIPES.is_dir():
        print("FAIL: %s not found" % RECIPES, file=sys.stderr)
        return 1
    recipes = sorted(RECIPES.rglob("*.yaml")) + sorted(RECIPES.rglob("*.yml"))
    recipes = [p for p in recipes if ".git" not in p.parts]
    if not recipes:
        print("FAIL: no recipe files found under %s" % RECIPES, file=sys.stderr)
        return 1

    sparkrun_bin = sparkrun_available(args.sparkrun)
    print("cglab registry validate — %d recipe(s)%s" % (
        len(recipes), "" if sparkrun_bin else "  [sparkrun not on PATH: structural checks only]"))
    print("image checks: %s" % ("live" if not args.no_network else "SKIPPED (--no-network)"))
    print("-" * 78)

    failed = 0
    for p in recipes:
        rel = p.relative_to(ROOT).as_posix()
        results = validate_recipe_file(p, sparkrun_bin)
        # image check
        try:
            import yaml as _y  # type: ignore
            ref = (_y.safe_load(p.read_text(encoding="utf-8")) or {}).get("container")
        except Exception:
            ref = None
        if not ref:
            results.append(("error", "no container reference to resolve"))
        elif args.no_network:
            results.append(("ok", "container '%s' (network check skipped)" % ref))
        else:
            ok, how, detail = check_image_ref(ref)
            results.append(("error" if not ok else "ok",
                            "container '%s' [%s]: %s" % (ref, how, detail)))
        errs = [m for k, m in results if k == "error"]
        ok = not errs
        if not ok:
            failed += 1
        print("[%s] %s" % ("PASS" if ok else "FAIL", rel))
        for k, m in results:
            print("        - %s" % m)
    print("-" * 78)
    if failed:
        print("RESULT: FAIL — %d/%d recipe(s) failed" % (failed, len(recipes)))
        return 1
    print("RESULT: PASS — %d/%d recipe(s) clean" % (len(recipes), len(recipes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
