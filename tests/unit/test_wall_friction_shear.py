"""フェーズ2の本せん断ワークフローのユニットテスト(MockRockyClient使用)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from poscap_calibration.models import ShearCondition, WallFrictionCondition
from poscap_calibration.rocky.client import RockyClient
from poscap_calibration.rocky.mock_client import MockRockyClient
from poscap_calibration.rocky.simulation_runner import read_shear_time_series
from poscap_calibration.state.state_manager import STATUS_COMPLETED, read_status
from poscap_calibration.wall_friction_analysis_excel import SHEAR_SHEET_HEADERS
from poscap_calibration.workflows.wall_friction_simulation import (
    run_wall_friction_shear_test,
    wall_shear_step_name,
    wall_shear_time_series_csv_path,
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
DISC_HEIGHT_M = 0.0030878720312570913


def _create_template(tmp_path: Path, name: str) -> Path:
    template_path = tmp_path / "templates" / name
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text("template", encoding="utf-8")
    files_dir = template_path.with_suffix(f"{template_path.suffix}.files")
    files_dir.mkdir()
    (files_dir / "data.bin").write_text("data", encoding="utf-8")
    return template_path


def _create_inlet_csv(tmp_path: Path) -> Path:
    inlet_path = tmp_path / "pre_shear" / "particles_inlet.csv"
    inlet_path.parent.mkdir(parents=True, exist_ok=True)
    inlet_path.write_text("x,y,z,size\n0.001,0.002,0.003,0.0001\n", encoding="utf-8")
    return inlet_path


def _run(tmp_path: Path, client: RockyClient, load_kpa: float = 3.0) -> dict:
    return run_wall_friction_shear_test(
        client,
        POWDER,
        WALL_CONDITION_1,
        load_kpa,
        template_project_path=_create_template(tmp_path, f"Shear_test_{load_kpa:g}kPa.rocky"),
        inlet_csv_path=_create_inlet_csv(tmp_path),
        disc_height_m=DISC_HEIGHT_M,
        output_root=tmp_path / "wall_friction_test",
        disc_geometry_name=DISC_GEOMETRY,
    )


def test_run_wall_friction_shear_test_sets_all_inputs(tmp_path: Path) -> None:
    client = MockRockyClient(completed=True)

    result = _run(tmp_path, client)

    output_root = tmp_path / "wall_friction_test"
    assert result["time_series_csv"] == wall_shear_time_series_csv_path(
        output_root, WALL_CONDITION_1, 3.0
    )
    assert result["time_series_csv"].is_file()
    assert result["applied_disc_height_m"] == pytest.approx(DISC_HEIGHT_M)

    call_names = [name for name, _ in client.calls]
    for required in (
        "set_powder_parameters",
        "set_wall_friction_parameters",
        "set_custom_inlet_csv",
        "set_geometry_translation_y",
    ):
        assert call_names.index(required) < call_names.index("run_simulation")

    assert ("set_powder_parameters", (0.44427, 0.66867, 0.73440)) in client.calls
    assert (
        "set_wall_friction_parameters",
        (0.11291, 0.11291, DISC_GEOMETRY, None),
    ) in client.calls
    assert ("set_geometry_translation_y", (DISC_GEOMETRY, DISC_HEIGHT_M)) in client.calls


def test_run_wall_friction_shear_test_writes_time_series_csv(tmp_path: Path) -> None:
    client = MockRockyClient(completed=True)

    result = _run(tmp_path, client)

    times, forces, moments = read_shear_time_series(result["time_series_csv"])
    assert len(times) == len(forces) == len(moments) == result["row_count"]
    assert times[0] == pytest.approx(result["time_range_s"][0])

    status = read_status(result["time_series_csv"].parent.parent)
    assert status["status"] == STATUS_COMPLETED
    assert status["load_kpa"] == pytest.approx(3.0)
    assert status["applied_disc_height_m"] == pytest.approx(DISC_HEIGHT_M)


def test_run_wall_friction_shear_test_fails_when_not_completed(tmp_path: Path) -> None:
    client = MockRockyClient(completed=False)

    with pytest.raises(RuntimeError):
        _run(tmp_path, client)

    status = read_status(
        tmp_path / "wall_friction_test" / "condition_01" / wall_shear_step_name(3.0)
    )
    assert status["status"] != STATUS_COMPLETED


def test_run_wall_friction_shear_test_requires_inlet_csv(tmp_path: Path) -> None:
    client = MockRockyClient(completed=True)

    with pytest.raises(FileNotFoundError):
        run_wall_friction_shear_test(
            client,
            POWDER,
            WALL_CONDITION_1,
            3.0,
            template_project_path=_create_template(tmp_path, "Shear_test_3kPa.rocky"),
            inlet_csv_path=tmp_path / "missing.csv",
            disc_height_m=DISC_HEIGHT_M,
            output_root=tmp_path / "wall_friction_test",
            disc_geometry_name=DISC_GEOMETRY,
        )


def test_wall_shear_paths_cover_all_loads(tmp_path: Path) -> None:
    """5/7 kPaへ展開してもパス生成が破綻しないことを確認する。"""
    output_root = tmp_path / "wall_friction_test"
    names = {
        load: wall_shear_time_series_csv_path(output_root, WALL_CONDITION_1, load).name
        for load in sorted(SHEAR_SHEET_HEADERS)
    }
    assert names == {
        3.0: "3kPa_WallShearTest_time.csv",
        5.0: "5kPa_WallShearTest_time.csv",
        7.0: "7kPa_WallShearTest_time.csv",
    }
    assert wall_shear_step_name(5.0) == "shear_5kpa"
