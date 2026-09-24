"""本せん断工程ワークフローと解析Excel解析のユニットテスト。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from poscap_calibration.models import ShearCondition
from poscap_calibration.rocky.mock_client import MockRockyClient
from poscap_calibration.rocky.simulation_runner import run_shear_test
from poscap_calibration.shear_analysis_excel import (
    get_shear_sheet_names,
    get_steady_slope_cells,
    find_time_series_columns,
)

WORKBOOK = (
    Path(__file__).parents[2] / "projects" / "0" / "shear_test" / "shear_analysis.xlsx"
)

CONDITION = ShearCondition(
    condition_id=1,
    rolling_resistance=0.2,
    dynamic_friction=0.2,
    static_friction=0.21966,
)
GEOMETRY = "FT4_ShearCell2_5deg_mm"
SHEAR_CELL_HEIGHT_M = 0.00228


def _create_template(tmp_path: Path, name: str = "Shear_3kPa.rocky") -> Path:
    template_path = tmp_path / "templates" / name
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text("template", encoding="utf-8")
    return template_path


def _create_inlet_csv(tmp_path: Path) -> Path:
    inlet_path = tmp_path / "pre_shear" / "particles_inlet.csv"
    inlet_path.parent.mkdir(parents=True, exist_ok=True)
    inlet_path.write_text(
        "x,y,z,size\n0.001,0.002,0.003,0.0001\n0.002,0.003,0.004,0.0002\n", encoding="utf-8"
    )
    return inlet_path


def test_run_shear_test_orchestrates_client_calls(tmp_path: Path) -> None:
    template_path = _create_template(tmp_path)
    inlet_path = _create_inlet_csv(tmp_path)
    output_root = tmp_path / "results"
    client = MockRockyClient(completed=True)

    csv_path = run_shear_test(
        client,
        CONDITION,
        load_kpa=3.0,
        template_project_path=template_path,
        inlet_csv_path=inlet_path,
        shear_cell_height_m=SHEAR_CELL_HEIGHT_M,
        output_root=output_root,
        shear_cell_geometry_name=GEOMETRY,
    )

    shear_directory = output_root / "condition_01" / "shear_3kpa"
    assert csv_path == shear_directory / "raw" / "3kPa_ShearTest_time.csv"
    assert csv_path.is_file()
    assert (shear_directory / "project" / "Shear_3kPa.rocky").is_file()
    assert (shear_directory / "shear_3kpa.log").is_file()
    assert template_path.read_text(encoding="utf-8") == "template"

    header = csv_path.read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("Date [s],Force Y (Lid Translational Motion) [N]")
    assert "Moment Y (Lid Rotational Motion) [N.m]" in header

    call_names = [name for name, _ in client.calls]
    assert call_names == [
        "connect",
        "open_project",
        "delete_results",
        "set_powder_parameters",
        "set_custom_inlet_csv",
        "set_geometry_translation_y",
        "get_geometry_translation_y",
        "save_project_as",
        "run_simulation",
        "get_curve",
        "get_curve",
        "disconnect",
    ]

    _, (inlet_argument,) = client.calls[4]
    assert inlet_argument.is_absolute()

    _, (geometry_name, height_value) = client.calls[5]
    assert geometry_name == GEOMETRY
    assert height_value == pytest.approx(SHEAR_CELL_HEIGHT_M)

    assert client.calls[9][1] == ("Lid Translational Motion", "Force Y")
    assert client.calls[10][1] == ("Lid Rotational Motion", "Moment Y")


def test_run_shear_test_writes_status(tmp_path: Path) -> None:
    template_path = _create_template(tmp_path)
    inlet_path = _create_inlet_csv(tmp_path)
    output_root = tmp_path / "results"

    run_shear_test(
        MockRockyClient(completed=True),
        CONDITION,
        load_kpa=5.0,
        template_project_path=_create_template(tmp_path, "Shear_5kPa.rocky"),
        inlet_csv_path=inlet_path,
        shear_cell_height_m=SHEAR_CELL_HEIGHT_M,
        output_root=output_root,
        shear_cell_geometry_name=GEOMETRY,
    )

    status = json.loads(
        (output_root / "condition_01" / "shear_5kpa" / "status.json").read_text(
            encoding="utf-8"
        )
    )
    assert status["status"] == "completed"
    assert status["load_kpa"] == 5.0
    assert status["row_count"] > 0
    assert status["applied_shear_cell_height_m"] == pytest.approx(SHEAR_CELL_HEIGHT_M)
    assert status["curves"]["moment"]["curve"] == "Moment Y"
    assert template_path.is_file()


def test_run_shear_test_rejects_inlet_csv_without_required_columns(tmp_path: Path) -> None:
    template_path = _create_template(tmp_path)
    inlet_path = tmp_path / "bad_inlet.csv"
    inlet_path.write_text("a,b,c\n1,2,3\n", encoding="utf-8")

    with pytest.raises(ValueError):
        run_shear_test(
            MockRockyClient(completed=True),
            CONDITION,
            load_kpa=3.0,
            template_project_path=template_path,
            inlet_csv_path=inlet_path,
            shear_cell_height_m=SHEAR_CELL_HEIGHT_M,
            output_root=tmp_path / "results",
            shear_cell_geometry_name=GEOMETRY,
        )


def test_run_shear_test_raises_when_not_completed(tmp_path: Path) -> None:
    template_path = _create_template(tmp_path)
    inlet_path = _create_inlet_csv(tmp_path)
    output_root = tmp_path / "results"

    with pytest.raises(RuntimeError):
        run_shear_test(
            MockRockyClient(completed=False),
            CONDITION,
            load_kpa=3.0,
            template_project_path=template_path,
            inlet_csv_path=inlet_path,
            shear_cell_height_m=SHEAR_CELL_HEIGHT_M,
            output_root=output_root,
            shear_cell_geometry_name=GEOMETRY,
        )

    status = json.loads(
        (output_root / "condition_01" / "shear_3kpa" / "status.json").read_text(
            encoding="utf-8"
        )
    )
    assert status["status"] == "failed"


@pytest.mark.skipif(not WORKBOOK.is_file(), reason="解析Excelが存在しない環境ではスキップ")
def test_shear_analysis_excel_locates_sheets_and_columns(tmp_path: Path) -> None:
    # Excelで開かれているとロックされるため、複製に対して検証する。
    workbook_copy = tmp_path / WORKBOOK.name
    try:
        shutil.copy2(WORKBOOK, workbook_copy)
    except PermissionError:  # pragma: no cover - Excelが排他ロック中の場合
        pytest.skip("解析Excelが他プロセスにロックされています。")

    sheet_names = get_shear_sheet_names(workbook_copy, 1)
    assert sheet_names == {3.0: "1.3", 5.0: "1.4", 7.0: "1.5"}

    columns = find_time_series_columns(workbook_copy, sheet_names[3.0])
    assert columns["time"] < columns["force_y"] < columns["moment_y"]
    assert columns["shear_stress_formula"] not in {
        columns["time"], columns["force_y"], columns["moment_y"]
    }
    assert columns["start_row"] >= 1

    assert get_steady_slope_cells(workbook_copy, 1) == {"raw": "N3", "corrected": "O3"}
