"""The default model follows the grounding mode (ADR 001)."""

from __future__ import annotations

from navigator.agent import NavigatorConfig
from navigator.cli import build_parser
from navigator.llm import default_model


def test_coords_defaults_to_sonnet() -> None:
    assert NavigatorConfig().model_id == "claude-sonnet-5"
    assert NavigatorConfig(grounding="coords").model_id == "claude-sonnet-5"


def test_som_defaults_to_opus() -> None:
    assert NavigatorConfig(grounding="som").model_id == "claude-opus-5"


def test_explicit_model_wins() -> None:
    assert NavigatorConfig(grounding="som", model="claude-haiku-4-5").model_id == "claude-haiku-4-5"


def test_unknown_grounding_falls_back() -> None:
    assert default_model("other") == "claude-opus-5"


def test_cli_leaves_model_unset_so_grounding_decides() -> None:
    args = build_parser().parse_args(["--repo", "a/b"])
    assert args.model is None
    assert NavigatorConfig(model=args.model, grounding=args.grounding).model_id == "claude-sonnet-5"
