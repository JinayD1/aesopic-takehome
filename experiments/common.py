"""Shared helpers for the experiments: oracle snapshots, scoring, stats, JSONL I/O."""

from __future__ import annotations

import json
import math
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXP_DIR = Path(__file__).resolve().parent
ORACLE_DIR = EXP_DIR / "oracle"
RESULTS_DIR = EXP_DIR / "results"
TRACES_DIR = EXP_DIR / "traces"
PAGES_DIR = EXP_DIR / "pages"

# --------------------------------------------------------------------------- #
# Oracle: GitHub REST API, fetched once and frozen to disk
# --------------------------------------------------------------------------- #


def _get(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "aesopic-navigator-experiments"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - fixed https host
        return json.loads(resp.read().decode())


def fetch_oracle(repo: str) -> dict[str, Any]:
    """Latest release per the API, with the tag dereferenced to its commit.

    GitHub's /git/ref/tags/<tag> returns a *tag object* for annotated tags;
    the release page shows the commit it points to, so we dereference.
    Repositories that have moved are followed to their new name.
    """
    repo_info = _get(f"https://api.github.com/repos/{repo}")
    full_name = repo_info["full_name"]
    rel = _get(f"https://api.github.com/repos/{full_name}/releases/latest")
    tag = rel["tag_name"]
    ref = _get(f"https://api.github.com/repos/{full_name}/git/ref/tags/{tag}")
    sha = ref["object"]["sha"]
    if ref["object"]["type"] == "tag":
        sha = _get(f"https://api.github.com/repos/{full_name}/git/tags/{sha}")["object"]["sha"]
    return {
        "requested_repo": repo,
        "repository": full_name,
        "version": rel.get("name") or tag,
        "tag": tag,
        "commit": sha,
        "commit_short": sha[:7],
        "author": (rel.get("author") or {}).get("login"),
        "published_at": rel.get("published_at"),
        "is_prerelease": rel.get("prerelease"),
        "asset_count": len(rel.get("assets") or []),
        "html_url": rel.get("html_url"),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def oracle_path(repo: str) -> Path:
    return ORACLE_DIR / (repo.replace("/", "-") + ".json")


def load_or_fetch_oracle(repo: str, refresh: bool = False) -> dict[str, Any]:
    path = oracle_path(repo)
    if path.is_file() and not refresh:
        return json.loads(path.read_text())  # type: ignore[no-any-return]
    data = fetch_oracle(repo)
    ORACLE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    return data


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


def norm_author(value: str | None) -> str | None:
    """'github-actions[bot]' (API) and 'github-actions' (page) are the same actor."""
    if not value:
        return None
    return re.sub(r"\[bot\]$", "", value.strip()).lower()


def norm_text(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", " ", value).strip().lower()


def field_correct(field: str, got: str | None, oracle: dict[str, Any]) -> bool | None:
    """Exact-match scoring per field. None when the oracle has nothing to compare."""
    if field == "version":
        g = norm_text(got)
        return g is not None and g in {norm_text(oracle["version"]), norm_text(oracle["tag"])}
    if field == "tag":
        return norm_text(got) == norm_text(oracle["tag"])
    if field == "commit":
        if not got:
            return False
        g = got.strip().lower()
        return len(g) >= 7 and oracle["commit"].lower().startswith(g)
    if field == "author":
        return norm_author(got) == norm_author(oracle["author"])
    if field == "repository":
        # Page headers render "owner / name"; compare without the spaces.
        g = re.sub(r"\s*/\s*", "/", got.strip()) if got else None
        return norm_text(g) == norm_text(oracle["repository"])
    return None


def char_error_rate(got: str | None, want: str) -> float:
    """Normalised Levenshtein distance; 1.0 when nothing was read."""
    if not got:
        return 1.0
    a, b = got.strip().lower(), want.strip().lower()
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / max(len(a), len(b), 1)


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """(rate, low, high) 95% Wilson score interval. Honest with small n."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def fmt_rate(successes: int, n: int) -> str:
    p, lo, hi = wilson(successes, n)
    return f"{successes}/{n} = {p:.0%} (95% CI {lo:.0%}–{hi:.0%})"


def median(values: list[float]) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


# --------------------------------------------------------------------------- #
# JSONL
# --------------------------------------------------------------------------- #


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")
