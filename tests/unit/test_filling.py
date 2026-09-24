"""充填工程ワークフローのユニットテスト(MockRockyClient使用)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from poscap_calibration.models import ShearCondition
from poscap_calibration.rocky.mock_client import MockRockyClient
from poscap_calibration.rocky.simulation_runner import run_filling

RAW_CSV = (
    Path(__file__).parents[1]
    / "reference_data"
    / "shear_condition_01"
    / "particle_generation_inlet_raw.csv"
)

CONDITION = ShearCondition(
    condition_id=1,
    rolling_resistance=0.2,
    dynamic_friction=0.2,
    static_friction=0.21966,
)


def _create_base_project(tmp_path: Path) -> Path:
    base_path = tmp_path / "base" / "Filling.rocky"
    base_path.parent.mkdir(parents=True, exist_ok=True)
    base_path.write_text("base", encoding="utf-8")

    files_dir = tmp_path / "base" / "Filling.rocky.files"
    files_dir.mkdir()
    (files_dir / "data.bin").write_text("data", encoding="utf-8")
    return base_path


def test_run_filling_sets_parameters_and_writes_outputs(tmp_path: Path) -> None:
    base_path = _create_base_project(tmp_path)
    output_root = tmp_path / "results"
    client = MockRockyClient(completed=True, particles_csv=RAW_CSV)

    converted_csv_path = run_filling(
        client,
        CONDITION,
        base_project_path=base_path,
        output_root=output_root,
        user_process_name="Split",
    )

    fill_directory = output_root / "condition_01" / "fill"
    assert converted_csv_path == fill_directory / "converted" / "particles_1ml_inlet.csv"
    assert converted_csv_path.is_file()
    assert (fill_directory / "raw" / "particles_1ml_raw.csv").is_file()
    assert (fill_directory / "project" / "Filling.rocky").is_file()
    assert (fill_directory / "project" / "Filling.rocky.files" / "data.bin").is_file()
    assert (fill_directory / "fill.log").is_file()

    assert converted_csv_path.read_text(encoding="utf-8").splitlines()[0] == "x,y,z,size"
    assert base_path.read_text(encoding="utf-8") == "base"

    call_names = [name for name, _ in client.calls]
    assert call_names == [
        "connect",
        "open_project",
        "delete_results",
        "set_powder_parameters",
        "save_project_as",
        "run_simulation",
        "export_user_process_particles",
        "disconnect",
    ]

    _, parameters = client.calls[3]
    assert parameters == (0.2, 0.2, 0.21966)

    _, (user_process_name, time_step) = client.calls[6]
    assert user_process_name == "Split"
    assert time_step == -1


def test_run_filling_writes_completed_status(tmp_path: Path) -> None:
    base_path = _create_base_project(tmp_path)
    output_root = tmp_path / "results"
    client = MockRockyClient(completed=True, particles_csv=RAW_CSV)

    run_filling(
        client,
        CONDITION,
        base_project_path=base_path,
        output_root=output_root,
        user_process_name="Split",
    )

    status_path = output_root / "condition_01" / "fill" / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))

    assert status["condition_id"] == 1
    assert status["step"] == "fill"
    assert status["status"] == "completed"
    assert status["particle_count"] > 0
    assert status["user_process_name"] == "Split"
    assert status["applied_parameters"]["static_friction"] == pytest.approx(0.21966)
    assert status["outputs"]["converted_csv"].endswith("particles_1ml_inlet.csv")


def test_run_filling_writes_failed_status_when_not_completed(tmp_path: Path) -> None:
    base_path = _create_base_project(tmp_path)
    output_root = tmp_path / "results"
    client = MockRockyClient(completed=False, particles_csv=RAW_CSV)

    with pytest.raises(RuntimeError):
        run_filling(
            client,
            CONDITION,
            base_project_path=base_path,
            output_root=output_root,
            user_process_name="Split",
        )

    status = json.loads(
        (output_root / "condition_01" / "fill" / "status.json").read_text(encoding="utf-8")
    )
    assert status["status"] == "failed"
    assert "error" in status

    call_names = [name for name, _ in client.calls]
    assert call_names[-1] == "disconnect"


def test_run_filling_uses_condition_specific_directory(tmp_path: Path) -> None:
    base_path = _create_base_project(tmp_path)
    output_root = tmp_path / "results"
    condition = ShearCondition(
        condition_id=9,
        rolling_resistance=0.7,
        dynamic_friction=0.7,
        static_friction=0.76881,
    )

    run_filling(
        MockRockyClient(completed=True, particles_csv=RAW_CSV),
        condition,
        base_project_path=base_path,
        output_root=output_root,
        user_process_name="Split",
    )

    assert (output_root / "condition_09" / "fill" / "status.json").is_file()
    assert not (output_root / "condition_01").exists()
