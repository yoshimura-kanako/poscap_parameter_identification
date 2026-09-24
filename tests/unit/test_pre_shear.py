"""プリせん断工程ワークフローのユニットテスト(MockRockyClient使用)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from poscap_calibration.models import ShearCondition
from poscap_calibration.rocky.mock_client import MockRockyClient
from poscap_calibration.rocky.simulation_runner import run_pre_shear

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
GEOMETRY = "FT4_ShearCell2_5deg_mm"


def _create_template(tmp_path: Path) -> Path:
    template_path = tmp_path / "templates" / "Pre_shear.rocky"
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text("template", encoding="utf-8")

    files_dir = tmp_path / "templates" / "Pre_shear.rocky.files"
    files_dir.mkdir()
    (files_dir / "data.bin").write_text("data", encoding="utf-8")
    return template_path


def _create_inlet_csv(tmp_path: Path) -> Path:
    inlet_path = tmp_path / "fill" / "particles_1ml_inlet.csv"
    inlet_path.parent.mkdir(parents=True, exist_ok=True)
    inlet_path.write_text("x,y,z,size\n0.001,0.002,0.003,0.0001\n", encoding="utf-8")
    return inlet_path


def test_run_pre_shear_orchestrates_client_calls(tmp_path: Path) -> None:
    template_path = _create_template(tmp_path)
    inlet_path = _create_inlet_csv(tmp_path)
    output_root = tmp_path / "results"
    client = MockRockyClient(completed=True, particles_csv=RAW_CSV)

    converted_csv_path = run_pre_shear(
        client,
        CONDITION,
        template_project_path=template_path,
        inlet_csv_path=inlet_path,
        output_root=output_root,
        shear_cell_geometry_name=GEOMETRY,
    )

    pre_shear_directory = output_root / "condition_01" / "pre_shear"
    assert converted_csv_path == pre_shear_directory / "converted" / "particles_inlet.csv"
    assert converted_csv_path.is_file()
    assert (pre_shear_directory / "raw" / "particles_raw.csv").is_file()
    assert (pre_shear_directory / "raw" / "shear_cell_height.json").is_file()
    assert (pre_shear_directory / "project" / "Pre_shear.rocky").is_file()
    assert (pre_shear_directory / "project" / "Pre_shear.rocky.files" / "data.bin").is_file()
    assert (pre_shear_directory / "pre_shear.log").is_file()

    assert converted_csv_path.read_text(encoding="utf-8").splitlines()[0] == "x,y,z,size"
    assert template_path.read_text(encoding="utf-8") == "template"

    call_names = [name for name, _ in client.calls]
    assert call_names == [
        "connect",
        "open_project",
        "delete_results",
        "set_powder_parameters",
        "set_custom_inlet_csv",
        "save_project_as",
        "run_simulation",
        "get_geometry_max_y",
        "export_user_process_particles",
        "disconnect",
    ]

    _, parameters = client.calls[3]
    assert parameters == (0.2, 0.2, 0.21966)

    # Particle Custom Inletへは絶対パスで設定する。
    _, (inlet_argument,) = client.calls[4]
    assert inlet_argument.is_absolute()
    assert inlet_argument == inlet_path.resolve()

    _, (geometry_name, geometry_time_step) = client.calls[7]
    assert geometry_name == GEOMETRY
    assert geometry_time_step == -1

    _, (user_process_name, time_step) = client.calls[8]
    assert user_process_name is None
    assert time_step == -1


def test_run_pre_shear_saves_shear_cell_height(tmp_path: Path) -> None:
    template_path = _create_template(tmp_path)
    inlet_path = _create_inlet_csv(tmp_path)
    output_root = tmp_path / "results"
    client = MockRockyClient(completed=True, particles_csv=RAW_CSV, geometry_max_y=0.0456)

    run_pre_shear(
        client,
        CONDITION,
        template_project_path=template_path,
        inlet_csv_path=inlet_path,
        output_root=output_root,
        shear_cell_geometry_name=GEOMETRY,
    )

    pre_shear_directory = output_root / "condition_01" / "pre_shear"
    height = json.loads(
        (pre_shear_directory / "raw" / "shear_cell_height.json").read_text(encoding="utf-8")
    )
    assert height["geometry"] == GEOMETRY
    assert height["maximum_y_m"] == pytest.approx(0.0456)
    assert height["unit"] == "m"
    assert height["time_s"] == pytest.approx(0.75)

    status = json.loads(
        (pre_shear_directory / "status.json").read_text(encoding="utf-8")
    )
    assert status["step"] == "pre_shear"
    assert status["status"] == "completed"
    assert status["particle_count"] > 0
    assert status["shear_cell_height"]["maximum_y_m"] == pytest.approx(0.0456)
    assert status["inlet_csv"] == str(inlet_path.resolve())

    log_text = (pre_shear_directory / "pre_shear.log").read_text(encoding="utf-8")
    assert "shear cell height" in log_text
    assert "0.0456" in log_text


def test_run_pre_shear_raises_when_inlet_csv_missing(tmp_path: Path) -> None:
    template_path = _create_template(tmp_path)
    client = MockRockyClient(completed=True, particles_csv=RAW_CSV)

    with pytest.raises(FileNotFoundError):
        run_pre_shear(
            client,
            CONDITION,
            template_project_path=template_path,
            inlet_csv_path=tmp_path / "missing.csv",
            output_root=tmp_path / "results",
            shear_cell_geometry_name=GEOMETRY,
        )

    assert client.calls == []


def test_run_pre_shear_writes_failed_status_when_not_completed(tmp_path: Path) -> None:
    template_path = _create_template(tmp_path)
    inlet_path = _create_inlet_csv(tmp_path)
    output_root = tmp_path / "results"
    client = MockRockyClient(completed=False, particles_csv=RAW_CSV)

    with pytest.raises(RuntimeError):
        run_pre_shear(
            client,
            CONDITION,
            template_project_path=template_path,
            inlet_csv_path=inlet_path,
            output_root=output_root,
            shear_cell_geometry_name=GEOMETRY,
        )

    status = json.loads(
        (output_root / "condition_01" / "pre_shear" / "status.json").read_text(
            encoding="utf-8"
        )
    )
    assert status["status"] == "failed"
    assert "error" in status

    call_names = [name for name, _ in client.calls]
    assert call_names[-1] == "disconnect"
