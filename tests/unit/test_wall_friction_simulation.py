"""フェーズ2の充填・プリせん断ワークフローのユニットテスト(MockRockyClient使用)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from poscap_calibration.config import WALL_SECTION, get_object_name, get_template_path
from poscap_calibration.models import ShearCondition, WallFrictionCondition
from poscap_calibration.rocky.mock_client import MockRockyClient
from poscap_calibration.state.state_manager import STATUS_COMPLETED, read_status
from poscap_calibration.workflows.wall_friction_simulation import (
    run_wall_friction_filling,
    run_wall_friction_pre_shear,
    wall_friction_fill_inlet_csv_path,
)

RAW_CSV = (
    Path(__file__).parents[1]
    / "reference_data"
    / "shear_condition_01"
    / "particle_generation_inlet_raw.csv"
)

POWDER = ShearCondition(
    condition_id=1,
    rolling_resistance=0.44427,
    dynamic_friction=0.66867,
    static_friction=0.73440,
)
WALL_CONDITION_1 = WallFrictionCondition(
    condition_id=1, dynamic_friction=0.11291, static_friction=0.11291
)
DISC_GEOMETRY = "Wall_Friction_Disc_24mm_5deg"


def _create_template(tmp_path: Path, name: str) -> Path:
    template_path = tmp_path / "templates" / name
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text("template", encoding="utf-8")
    files_dir = template_path.with_suffix(f"{template_path.suffix}.files")
    files_dir.mkdir()
    (files_dir / "data.bin").write_text("data", encoding="utf-8")
    return template_path


def _create_inlet_csv(tmp_path: Path) -> Path:
    inlet_path = tmp_path / "fill" / "particles_1ml_inlet.csv"
    inlet_path.parent.mkdir(parents=True, exist_ok=True)
    inlet_path.write_text("x,y,z,size\n0.001,0.002,0.003,0.0001\n", encoding="utf-8")
    return inlet_path


def test_config_provides_wall_object_names() -> None:
    assert get_object_name(WALL_SECTION, "wall_disc_geometry") == DISC_GEOMETRY
    assert get_object_name(WALL_SECTION, "fill_user_process") == "Split"
    assert get_object_name(WALL_SECTION, "wall_material") is None
    # 充填テンプレートはせん断試験と共通。
    assert get_template_path(WALL_SECTION, "fill").name == "Filling.rocky"
    assert "shear" in get_template_path(WALL_SECTION, "fill").parts


def test_run_wall_friction_filling_uses_root_fill_output(tmp_path: Path) -> None:
    template_path = _create_template(tmp_path, "Filling.rocky")
    output_root = tmp_path / "wall_friction_test"
    client = MockRockyClient(completed=True, particles_csv=RAW_CSV)

    converted_csv_path = run_wall_friction_filling(
        client, POWDER, template_path, output_root, "Split"
    )

    assert converted_csv_path == wall_friction_fill_inlet_csv_path(output_root)
    assert converted_csv_path.is_file()
    assert ("set_powder_parameters", (0.44427, 0.66867, 0.73440)) in client.calls
    assert ("export_user_process_particles", ("Split", -1)) in client.calls


def test_run_wall_friction_pre_shear_sets_both_parameter_sets(tmp_path: Path) -> None:
    template_path = _create_template(tmp_path, "Pre_shear_9kPa.rocky")
    inlet_path = _create_inlet_csv(tmp_path)
    output_root = tmp_path / "wall_friction_test"
    client = MockRockyClient(completed=True, particles_csv=RAW_CSV, geometry_max_y=0.00231)

    result = run_wall_friction_pre_shear(
        client,
        POWDER,
        WALL_CONDITION_1,
        template_project_path=template_path,
        inlet_csv_path=inlet_path,
        output_root=output_root,
        disc_geometry_name=DISC_GEOMETRY,
    )

    condition_directory = output_root / "condition_01" / "pre_shear"
    assert result["converted_csv"] == condition_directory / "converted" / "particles_inlet.csv"
    assert result["converted_csv"].is_file()
    assert result["disc_height_json"].is_file()
    assert result["particle_count"] > 0

    call_names = [name for name, _ in client.calls]
    assert call_names.index("set_powder_parameters") < call_names.index("run_simulation")
    assert call_names.index("set_wall_friction_parameters") < call_names.index("run_simulation")
    assert (
        "set_wall_friction_parameters",
        (0.11291, 0.11291, DISC_GEOMETRY, None),
    ) in client.calls

    height = json.loads(result["disc_height_json"].read_text(encoding="utf-8"))
    assert height["geometry"] == DISC_GEOMETRY

    status = read_status(condition_directory)
    assert status["status"] == STATUS_COMPLETED
    assert status["requested_wall_parameters"]["dynamic_friction"] == pytest.approx(0.11291)
    assert status["applied_powder_parameters"]["rolling_resistance"] == pytest.approx(0.44427)


def test_run_wall_friction_pre_shear_supports_other_conditions(tmp_path: Path) -> None:
    """条件2・3も同じ経路で別フォルダへ出力できる。"""
    template_path = _create_template(tmp_path, "Pre_shear_9kPa.rocky")
    inlet_path = _create_inlet_csv(tmp_path)
    output_root = tmp_path / "wall_friction_test"

    for condition in (
        WallFrictionCondition(condition_id=2, dynamic_friction=0.22582, static_friction=0.22582),
        WallFrictionCondition(condition_id=3, dynamic_friction=0.33873, static_friction=0.33873),
    ):
        client = MockRockyClient(completed=True, particles_csv=RAW_CSV)
        result = run_wall_friction_pre_shear(
            client,
            POWDER,
            condition,
            template_project_path=template_path,
            inlet_csv_path=inlet_path,
            output_root=output_root,
            disc_geometry_name=DISC_GEOMETRY,
        )
        assert condition.directory_name in str(result["converted_csv"])

    assert (output_root / "condition_02" / "pre_shear").is_dir()
    assert (output_root / "condition_03" / "pre_shear").is_dir()


def test_run_wall_friction_pre_shear_requires_inlet_csv(tmp_path: Path) -> None:
    template_path = _create_template(tmp_path, "Pre_shear_9kPa.rocky")
    client = MockRockyClient(completed=True, particles_csv=RAW_CSV)

    with pytest.raises(FileNotFoundError):
        run_wall_friction_pre_shear(
            client,
            POWDER,
            WALL_CONDITION_1,
            template_project_path=template_path,
            inlet_csv_path=tmp_path / "missing.csv",
            output_root=tmp_path / "out",
            disc_geometry_name=DISC_GEOMETRY,
        )


def test_run_wall_friction_pre_shear_fails_when_simulation_incomplete(tmp_path: Path) -> None:
    template_path = _create_template(tmp_path, "Pre_shear_9kPa.rocky")
    inlet_path = _create_inlet_csv(tmp_path)
    client = MockRockyClient(completed=False, particles_csv=RAW_CSV)

    with pytest.raises(RuntimeError):
        run_wall_friction_pre_shear(
            client,
            POWDER,
            WALL_CONDITION_1,
            template_project_path=template_path,
            inlet_csv_path=inlet_path,
            output_root=tmp_path / "out",
            disc_geometry_name=DISC_GEOMETRY,
        )
