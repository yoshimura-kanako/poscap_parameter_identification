"""安息角シミュレーションワークフローのユニットテスト(MockRockyClient使用)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from poscap_calibration.condition_table import get_shear_condition
from poscap_calibration.models import ShearCondition
from poscap_calibration.rocky.mock_client import MockRockyClient
from poscap_calibration.workflows.phase1_saor import (
    create_saor_analysis_workbook,
    run_saor,
)

EXCEL_TEMPLATE = (
    Path(__file__).parents[2] / "templates" / "excel" / "saor_analysis_template.xlsx"
)
DISTRIBUTION_CSV = (
    Path(__file__).parents[2] / "input" / "particle_distribution" / "test_distribution.csv"
)

CONDITION = ShearCondition(
    condition_id=1,
    rolling_resistance=0.2,
    dynamic_friction=0.2,
    static_friction=0.21966,
)


def _create_template(tmp_path: Path) -> Path:
    template_path = tmp_path / "templates" / "SAOR.rocky"
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text("template", encoding="utf-8")
    return template_path


def test_create_saor_analysis_workbook_copies_template(tmp_path: Path) -> None:
    saor_test_directory = tmp_path / "projects" / "0" / "saor_test"
    workbook_path = create_saor_analysis_workbook(EXCEL_TEMPLATE, saor_test_directory)

    assert workbook_path == saor_test_directory / "saor_analysis.xlsx"
    assert workbook_path.is_file()
    assert workbook_path.stat().st_size == EXCEL_TEMPLATE.stat().st_size


def test_create_saor_analysis_workbook_keeps_existing_copy(tmp_path: Path) -> None:
    saor_test_directory = tmp_path / "projects" / "0" / "saor_test"
    workbook_path = create_saor_analysis_workbook(EXCEL_TEMPLATE, saor_test_directory)
    workbook_path.write_text("edited", encoding="utf-8")

    again = create_saor_analysis_workbook(EXCEL_TEMPLATE, saor_test_directory)

    assert again == workbook_path
    assert workbook_path.read_text(encoding="utf-8") == "edited"


def test_saor_workbook_provides_condition_parameters(tmp_path: Path) -> None:
    """SAORの条件表は見出しが1行構成でも読み取れる。"""
    workbook_path = create_saor_analysis_workbook(EXCEL_TEMPLATE, tmp_path / "projects" / "0")

    condition = get_shear_condition(workbook_path, 1)

    assert condition.condition_id == 1
    assert condition.rolling_resistance == pytest.approx(0.2)
    assert condition.dynamic_friction == pytest.approx(0.2)
    assert condition.static_friction == pytest.approx(0.21966)


def test_run_saor_orchestrates_client_calls(tmp_path: Path) -> None:
    template_path = _create_template(tmp_path)
    output_root = tmp_path / "results"
    client = MockRockyClient(completed=True)

    project_path = run_saor(
        client,
        CONDITION,
        template_project_path=template_path,
        distribution_csv_path=DISTRIBUTION_CSV,
        output_root=output_root,
        post_process=False,
    )

    saor_directory = output_root / "condition_01"
    assert project_path == saor_directory / "project" / "SAOR.rocky"
    assert project_path.is_file()
    assert (saor_directory / "saor.log").is_file()
    assert (saor_directory / "status.json").is_file()
    assert template_path.read_text(encoding="utf-8") == "template"

    call_names = [name for name, _ in client.calls]
    assert call_names == [
        "connect",
        "open_project",
        "delete_results",
        "set_particle_property",
        "set_powder_parameters",
        "save_project_as",
        "run_simulation",
        "disconnect",
    ]

    _, (property_name, distribution) = client.calls[3]
    assert property_name == "size_distribution"
    assert distribution[0][1] == pytest.approx(100.0)

    _, parameters = client.calls[4]
    assert parameters == (0.2, 0.2, 0.21966)


def test_run_saor_writes_completed_status(tmp_path: Path) -> None:
    template_path = _create_template(tmp_path)
    output_root = tmp_path / "results"

    run_saor(
        MockRockyClient(completed=True),
        CONDITION,
        template_project_path=template_path,
        distribution_csv_path=DISTRIBUTION_CSV,
        output_root=output_root,
        post_process=False,
    )

    status = json.loads(
        (output_root / "condition_01" / "status.json").read_text(encoding="utf-8")
    )
    assert status["step"] == "saor"
    assert status["status"] == "completed"
    assert status["condition_id"] == 1
    assert status["applied_parameters"]["static_friction"] == pytest.approx(0.21966)
    assert status["distribution_point_count"] > 0
    assert status["outputs"]["project"].endswith("SAOR.rocky")


def test_run_saor_writes_failed_status_when_not_completed(tmp_path: Path) -> None:
    template_path = _create_template(tmp_path)
    output_root = tmp_path / "results"
    client = MockRockyClient(completed=False)

    with pytest.raises(RuntimeError):
        run_saor(
            client,
            CONDITION,
            template_project_path=template_path,
            distribution_csv_path=DISTRIBUTION_CSV,
            output_root=output_root,
            post_process=False,
        )

    status = json.loads(
        (output_root / "condition_01" / "status.json").read_text(encoding="utf-8")
    )
    assert status["status"] == "failed"
    assert "error" in status

    call_names = [name for name, _ in client.calls]
    assert call_names[-1] == "disconnect"


def test_run_saor_raises_when_template_missing(tmp_path: Path) -> None:
    client = MockRockyClient(completed=True)

    with pytest.raises(FileNotFoundError):
        run_saor(
            client,
            CONDITION,
            template_project_path=tmp_path / "missing.rocky",
            distribution_csv_path=DISTRIBUTION_CSV,
            output_root=tmp_path / "results",
        )

    assert client.calls == []


def test_run_saor_uses_condition_specific_directory(tmp_path: Path) -> None:
    template_path = _create_template(tmp_path)
    output_root = tmp_path / "results"
    condition = ShearCondition(
        condition_id=9,
        rolling_resistance=0.7,
        dynamic_friction=0.7,
        static_friction=0.76881,
    )

    run_saor(
        MockRockyClient(completed=True),
        condition,
        template_project_path=template_path,
        distribution_csv_path=DISTRIBUTION_CSV,
        output_root=output_root,
        post_process=False,
    )

    assert (output_root / "condition_09" / "status.json").is_file()
    assert not (output_root / "condition_01").exists()


def test_run_saor_runs_post_process_in_same_session(tmp_path: Path) -> None:
    """Rockyを再起動せず、同一セッション内でポスト処理を実行する。"""
    template_path = _create_template(tmp_path)
    output_root = tmp_path / "results"
    stub_script = tmp_path / "stub_post_process.py"
    stub_script.write_text(
        """
import json
import os

import numpy as np
import pandas as pd


def post_process(project, results_folder):
    timeset = [0.0, 1.0]
    _ = 'time_step=timeset[-1] line_terminator='
    return np.array([[0.0, 0.1, 0.2, 0.15, 0.3, 0.4]]), 33.0, 29.0


def dump_to_file(data, top_angle, bottom_angle, results_folder):
    pd.DataFrame(data).to_csv(
        os.path.join(results_folder, 'experiment_data_points.csv'), index=False
    )
    with open(os.path.join(results_folder, 'angles.json'), 'w') as handle:
        json.dump({'SAOR_from_top': top_angle, 'SAOR_from_bottom': bottom_angle}, handle)
    with open(os.path.join(results_folder, 'Experiment_saor.png'), 'wb') as handle:
        handle.write(b'png')


project = app.GetProject()
""",
        encoding="utf-8",
    )

    client = MockRockyClient(completed=True)
    run_saor(
        client,
        CONDITION,
        template_project_path=template_path,
        distribution_csv_path=DISTRIBUTION_CSV,
        output_root=output_root,
        post_process_script_path=stub_script,
    )

    call_names = [name for name, _ in client.calls]
    # get_project がシミュレーション後・切断前にあることが同一セッション実行の証拠。
    assert call_names.index("run_simulation") < call_names.index("get_project")
    assert call_names.index("get_project") < call_names.index("disconnect")
    assert call_names.count("connect") == 1

    condition_directory = output_root / "condition_01"
    post_directory = condition_directory / "Results" / "saor"
    for filename in ("angles.json", "experiment_data_points.csv", "Experiment_saor.png"):
        assert (post_directory / filename).is_file()

    status = json.loads((condition_directory / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "completed"
    assert status["post_process_result"]["saor_from_top_deg"] == pytest.approx(33.0)
    assert status["outputs"]["post_process_directory"].endswith("saor")
