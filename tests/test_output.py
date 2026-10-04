"""The CLI's JSON: compact by default, the whole record behind --full."""

from __future__ import annotations

from navigator.schemas import (
    Extraction,
    FieldCorrection,
    ReleaseInfo,
    RunMeta,
    RunResult,
    RunStatus,
    Usage,
    VerificationOutcome,
)


def _result(corrections: list[FieldCorrection] | None = None) -> RunResult:
    release = ReleaseInfo(repository="openclaw/openclaw", tag="v2026.9.8", commit="fc23bc8")
    vision = release.model_copy(update={"commit": "fc23b8c"})
    outcome = VerificationOutcome.CORRECTED if corrections else VerificationOutcome.AGREE
    return RunResult(
        repository="openclaw/openclaw",
        latest_release=release,
        extraction=Extraction(
            vision_read=vision,
            verification=outcome,
            corrections=corrections or [],
            notes_corrected=True,
            notes_change="2 words replaced",
        ),
        run=RunMeta(
            model="m",
            grounding="coords",
            extraction="verified",
            steps=5,
            status=RunStatus.SUCCESS,
            usage=Usage(input_tokens=10, api_calls=7),
            cost_usd=0.17,
            wall_time_s=41.3,
            trace_dir="runs/x",
            started_at="2026-10-03T22:58:30+00:00",
        ),
    )


class TestCompactOutput:
    def test_drops_audit_trail_and_bookkeeping(self) -> None:
        out = _result().to_output()
        assert set(out) == {"repository", "latest_release", "run"}
        assert "repository" not in out["latest_release"]  # not repeated
        assert out["latest_release"]["commit"] == "fc23bc8"  # the verified value
        assert "usage" not in out["run"] and "started_at" not in out["run"]

    def test_keeps_what_verification_decided(self) -> None:
        fix = FieldCorrection(field="commit", vision_value="fc23b8c", text_value="fc23bc8")
        out = _result([fix]).to_output()
        assert out["run"]["verification"] == "corrected"
        assert out["run"]["corrections"] == [fix.model_dump()]
        assert out["run"]["notes_change"] == "2 words replaced"
        assert out["latest_release"]["commit"] == "fc23bc8"

    def test_errors_only_when_present(self) -> None:
        r = _result()
        assert "errors" not in r.to_output()
        r.errors.append("step 3: label 42 is not on screen")
        assert r.to_output()["errors"] == ["step 3: label 42 is not on screen"]


class TestFullOutput:
    def test_full_is_the_whole_record(self) -> None:
        out = _result().to_output(full=True)
        assert out["extraction"]["vision_read"]["commit"] == "fc23b8c"
        assert out["run"]["usage"]["api_calls"] == 7
        assert out["run"]["started_at"].startswith("2026-10-03")
