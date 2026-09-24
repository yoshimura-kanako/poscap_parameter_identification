"""通し実行パイプラインの単体テスト(Rockyは使わない)。"""

from __future__ import annotations

import json
import sys

import pytest

from poscap_calibration.project_layout import ProjectLayout
from poscap_calibration.state.state_manager import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_SKIPPED,
)
from poscap_calibration.workflows.pipeline import (
    PHASE_KEYS,
    STAGES,
    PipelineError,
    PipelineOptions,
    Stage,
    format_summary,
    run_pipeline,
    run_stage,
    select_stages,
)


@pytest.fixture
def options(tmp_path):
    distribution_csv = tmp_path / "distribution.csv"
    distribution_csv.write_text("particle_size,cumulative_mass_percent\n1,100\n", encoding="utf-8")
    return PipelineOptions(
        layout=ProjectLayout("0", tmp_path / "projects"),
        peak_ratio=1.05,
        shear_target=0.69898,
        saor_target=42.9,
        distribution_csv=distribution_csv,
    )


def _echo_stage(key: str = "echo", phase: str = "phase0", marker: str = "done") -> Stage:
    return Stage(
        key=key,
        phase=phase,
        title=f"テスト工程 {key}",
        command=lambda options: [
            sys.executable,
            "-c",
            f"from pathlib import Path; "
            f"p = Path(r'{options.project_directory / marker}'); "
            f"p.parent.mkdir(parents=True, exist_ok=True); p.write_text('ok'); print('{marker}')",
        ],
        outputs=lambda options: (options.project_directory / marker,),
    )


def _failing_stage(key: str = "boom", phase: str = "phase0") -> Stage:
    return Stage(
        key=key,
        phase=phase,
        title=f"失敗する工程 {key}",
        command=lambda options: [sys.executable, "-c", "raise SystemExit(3)"],
    )


def test_all_stages_belong_to_known_phases():
    assert {stage.phase for stage in STAGES} <= set(PHASE_KEYS)
    assert len({stage.key for stage in STAGES}) == len(STAGES)


def test_select_stages_filters_by_phase_and_range():
    phase2 = select_stages(phases=["phase2"])
    assert [stage.phase for stage in phase2] == ["phase2"] * len(phase2)

    sliced = select_stages(start_from="phase1_rsm_shear", stop_after="phase1_overlay")
    assert [stage.key for stage in sliced] == [
        "phase1_rsm_shear",
        "phase1_rsm_saor",
        "phase1_overlay",
    ]

    with pytest.raises(ValueError):
        select_stages(phases=["phase9"])


def test_run_stage_records_status_and_log(options, tmp_path):
    stage = _echo_stage()
    status = run_stage(options, stage)

    assert status["status"] == STATUS_COMPLETED
    stage_directory = options.project_directory / "pipeline" / stage.key
    assert json.loads((stage_directory / "status.json").read_text(encoding="utf-8"))[
        "status"
    ] == STATUS_COMPLETED
    assert "done" in (stage_directory / "stage.log").read_text(encoding="utf-8")


def test_run_stage_skips_when_outputs_exist(options):
    stage = _echo_stage()
    run_stage(options, stage)
    assert run_stage(options, stage)["status"] == STATUS_SKIPPED
    # --force 相当では再実行する。
    assert run_stage(options, stage, force=True)["status"] == STATUS_COMPLETED


def test_run_stage_reruns_when_output_is_missing(options):
    stage = _echo_stage()
    run_stage(options, stage)
    (options.project_directory / "done").unlink()
    assert run_stage(options, stage)["status"] == STATUS_COMPLETED


def test_failing_stage_keeps_error_excerpt(options):
    with pytest.raises(PipelineError):
        run_stage(options, _failing_stage())

    stage_directory = options.project_directory / "pipeline" / "boom"
    status = json.loads((stage_directory / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == STATUS_FAILED
    assert status["return_code"] == 3
    assert status["error_excerpt"]


def test_run_pipeline_stops_at_first_failure(options):
    stages = [_echo_stage("first", marker="first"), _failing_stage(), _echo_stage("last", marker="last")]
    summary = run_pipeline(options, stages=stages)

    assert summary["status"] == STATUS_FAILED
    assert summary["stopped_at_stage"] == "boom"
    assert "last" not in summary["stages"]
    assert (options.project_directory / "pipeline_summary.json").is_file()
    assert "失敗" in format_summary(summary)


def test_run_pipeline_can_continue_after_failure(options):
    stages = [_failing_stage(), _echo_stage("last", marker="last")]
    summary = run_pipeline(options, stages=stages, stop_on_error=False)

    assert summary["failed_stages"] == ["boom"]
    assert summary["stages"]["last"]["status"] == STATUS_COMPLETED


def test_dry_run_does_not_execute(options):
    stages = [_echo_stage()]
    summary = run_pipeline(options, stages=stages, dry_run=True)

    assert summary["planned_stages"][0]["completed"] is False
    assert not (options.project_directory / "done").exists()


def test_phase2_requires_identified_parameters(options):
    with pytest.raises(PipelineError, match="フェーズ1の同定値"):
        options.powder_parameter_arguments()
