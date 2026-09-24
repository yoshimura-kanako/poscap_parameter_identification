#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""条件別の本せん断シミュレーション(3/5/7 kPa)を実行し、解析Excelへ反映する(手順書1.2.7)。

実行例:
    python scripts/run_shear_test.py --condition-ids 1 --loads 3
    python scripts/run_shear_test.py --condition-ids 1 --loads 3 5 7
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from poscap_calibration.condition_table import get_shear_condition
from poscap_calibration.project_layout import ProjectLayout
from poscap_calibration.rocky.client import PyRockyClient
from poscap_calibration.rocky.simulation_runner import read_shear_time_series, run_shear_test
from poscap_calibration.shear_analysis_excel import update_and_recalculate

ROCKY_EXECUTABLE_PATH = Path(r"C:\Program Files\ANSYS Inc\v252\Rocky\bin\Rocky.exe")
DEFAULT_PROJECT_ID = "0"
DEFAULT_PROJECT_ROOT = Path("projects")
CONDITION_TABLE_FILENAME = "shear_analysis.xlsx"
SHEAR_CELL_GEOMETRY_NAME = "FT4_ShearCell2_5deg_mm"
TEMPLATE_DIRECTORY = Path("templates/rocky/shear")
#: 荷重[kPa]と本せん断テンプレートの対応。
TEMPLATE_BY_LOAD: dict[float, str] = {
    3.0: "Shear_3kPa.rocky",
    5.0: "Shear_5kPa.rocky",
    7.0: "Shear_7kPa.rocky",
}
PRE_SHEAR_INLET_RELATIVE_PATH = Path("pre_shear/converted/particles_inlet.csv")
PRE_SHEAR_HEIGHT_RELATIVE_PATH = Path("pre_shear/raw/shear_cell_height.json")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--condition-ids", type=int, nargs="+", default=[1])
    parser.add_argument(
        "--loads", type=float, nargs="+", default=[3.0, 5.0, 7.0],
        help="実行する荷重[kPa](テンプレートと対応)",
    )
    parser.add_argument("--template-dir", type=Path, default=TEMPLATE_DIRECTORY)
    parser.add_argument("--geometry", default=SHEAR_CELL_GEOMETRY_NAME)
    parser.add_argument(
        "--skip-excel", action="store_true",
        help="解析Excelへの反映を行わない(Rocky実行のみ)",
    )
    parser.add_argument("--headless", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    layout = ProjectLayout(arguments.project_id, arguments.project_root)
    workbook_path = layout.shear_workbook
    output_root = layout.shear_test_directory

    if not ROCKY_EXECUTABLE_PATH.is_file():
        raise FileNotFoundError(f"Rocky実行ファイルが見つかりません: {ROCKY_EXECUTABLE_PATH}")
    if not workbook_path.is_file():
        raise FileNotFoundError(f"解析Excelが見つかりません: {workbook_path}")

    for condition_id in arguments.condition_ids:
        condition = get_shear_condition(workbook_path, condition_id)
        condition_root = output_root / condition.directory_name
        inlet_csv_path = condition_root / PRE_SHEAR_INLET_RELATIVE_PATH
        height_json_path = condition_root / PRE_SHEAR_HEIGHT_RELATIVE_PATH

        if not height_json_path.is_file():
            raise FileNotFoundError(
                f"条件{condition_id}: プリせん断のせん断セル高さが見つかりません: {height_json_path}"
            )
        height = json.loads(height_json_path.read_text(encoding="utf-8"))
        shear_cell_height_m = float(height["maximum_y_m"])

        print(
            f"[RUN] 条件{condition.condition_id}: "
            f"転がり抵抗={condition.rolling_resistance} "
            f"動摩擦={condition.dynamic_friction} "
            f"静止摩擦={condition.static_friction}"
        )
        print(f"      入力CSV       : {inlet_csv_path}")
        print(f"      せん断セル高さ: {shear_cell_height_m} m")

        time_series_by_load: dict[float, tuple[list[float], list[float], list[float]]] = {}
        csv_paths: dict[str, str] = {}
        for load_kpa in arguments.loads:
            template_name = TEMPLATE_BY_LOAD.get(load_kpa)
            if template_name is None:
                raise ValueError(
                    f"荷重{load_kpa}kPaに対応するテンプレートがありません。"
                    f"対応可能な荷重: {sorted(TEMPLATE_BY_LOAD)}"
                )
            template_path = arguments.template_dir / template_name
            if not template_path.is_file():
                raise FileNotFoundError(
                    f"条件{condition_id} 荷重{load_kpa}kPa: "
                    f"テンプレートが見つかりません: {template_path}"
                )

            client = PyRockyClient(str(ROCKY_EXECUTABLE_PATH), headless=arguments.headless)
            csv_path = run_shear_test(
                client,
                condition,
                load_kpa=load_kpa,
                template_project_path=template_path,
                inlet_csv_path=inlet_csv_path,
                shear_cell_height_m=shear_cell_height_m,
                output_root=output_root,
                shear_cell_geometry_name=arguments.geometry,
            )
            csv_paths[f"{load_kpa:g}"] = str(csv_path)
            time_series_by_load[load_kpa] = read_shear_time_series(csv_path)
            print(f"[OK] 条件{condition.condition_id} 荷重{load_kpa}kPa: {csv_path}")

        # 今回実行しなかった荷重は、既存の実行結果があればExcel反映に再利用する。
        for load_kpa in sorted(TEMPLATE_BY_LOAD):
            if load_kpa in time_series_by_load:
                continue
            existing_csv = (
                condition_root
                / f"shear_{load_kpa:g}kpa"
                / "raw"
                / f"{load_kpa:g}kPa_ShearTest_time.csv"
            )
            if existing_csv.is_file():
                csv_paths[f"{load_kpa:g}"] = str(existing_csv)
                time_series_by_load[load_kpa] = read_shear_time_series(existing_csv)
                print(f"[USE] 条件{condition.condition_id} 荷重{load_kpa}kPa: 既存結果を使用 {existing_csv}")

        summary: dict[str, object] = {
            "condition_id": condition.condition_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "parameters": {
                "rolling_resistance": condition.rolling_resistance,
                "dynamic_friction": condition.dynamic_friction,
                "static_friction": condition.static_friction,
            },
            "inlet_csv": str(inlet_csv_path.resolve()),
            "shear_cell_height_m": shear_cell_height_m,
            "templates": {
                f"{load:g}": str(arguments.template_dir / TEMPLATE_BY_LOAD[load])
                for load in sorted(time_series_by_load)
            },
            "rocky_projects": {
                f"{load:g}": str(
                    condition_root / f"shear_{load:g}kpa" / "project" / TEMPLATE_BY_LOAD[load]
                )
                for load in sorted(time_series_by_load)
            },
            "time_series_csv": csv_paths,
            "analysis_workbook": str(workbook_path.resolve()),
        }

        if arguments.skip_excel:
            summary["excel"] = {"recalculated": False, "skipped": True}
        else:
            print("[RUN] 解析Excelへ反映しています...")
            summary["excel"] = update_and_recalculate(
                workbook_path, condition.condition_id, time_series_by_load
            )

        summary_path = condition_root / "shear_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print(f"[OK] サマリを保存しました: {summary_path}")

    return 0


def _read_time_series(csv_path: Path) -> tuple[list[float], list[float], list[float]]:
    return read_shear_time_series(csv_path)


if __name__ == "__main__":
    raise SystemExit(main())
