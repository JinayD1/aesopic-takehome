"""Live smoke test: a real navigation scored against the GitHub API.

Opt-in: ``pytest -m live``. Needs network and ANTHROPIC_API_KEY. Costs ~$0.20.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from experiments.common import field_correct, load_or_fetch_oracle
from navigator import prompts
from navigator.agent import Navigator, NavigatorConfig
from navigator.schemas import RunStatus

pytestmark = pytest.mark.live


@pytest.fixture(scope="module", autouse=True)
def _env() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")


def test_openclaw_release_matches_api(tmp_path: Path) -> None:
    oracle = load_or_fetch_oracle("openclaw/openclaw", refresh=True)
    cfg = NavigatorConfig(trace_root=tmp_path)
    result = Navigator(cfg).run(
        prompts.repo_goal("openclaw/openclaw"), "https://github.com", "live-test"
    )
    assert result.run.status is RunStatus.SUCCESS, result.run.status_detail
    assert result.repository == oracle["repository"]
    rel = result.latest_release
    assert rel is not None
    assert field_correct("tag", rel.tag, oracle), (rel.tag, oracle["tag"])
    assert field_correct("commit", rel.commit, oracle), (rel.commit, oracle["commit_short"])
    assert field_correct("author", rel.author, oracle), (rel.author, oracle["author"])
    assert result.run.steps <= 10
    assert result.run.cost_usd < 1.0
