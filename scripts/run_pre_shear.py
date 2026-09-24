#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""条件別のプリせん断シミュレーションを実行する(手順書1.2.7)。

実行例:
    python scripts/run_pre_shear.py --condition-ids 1
    python scripts/run_pre_shear.py --condition-ids 1 2 3 --headless
"""

from __future__ import annotations

import argparse
from pathlib import Path

from poscap_calibration.condition_table import get_shear_condition
from poscap_calibration.project_layout import ProjectLayout
from poscap_calibration.rocky.client import PyRockyClient
from poscap_calibration.rocky.simulation_runner import run_pre_shear

ROCKY_EXECUTABLE_PATH = Path(r"C:\Program Files\ANSYS Inc\v252\Rocky\bin\Rocky.exe")
DEFAULT_PROJECT_ID = "0"
DEFAULT_PROJECT_ROOT = Path("projects")
DEFAULT_TEMPLATE_PROJECT_PATH = Path("templates/rocky/shear/Pre_shear.rocky")
CONDITION_TABLE_FILENAME = "shear_analysis.xlsx"
# docs/Rocky.md 8.4節のせん断セルGeometry名。
SHEAR_CELL_GEOMETRY_NAME = "FT4_ShearCell2_5deg_mm"
# 充填工程(run_filling.py)が出力するParticle Custom Inlet CSVの相対パス。
FILLING_INLET_RELATIVE_PATH = Path("fill/converted/particles_1ml_inlet.csv")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument(
        "--condition-ids", type=int, nargs="+", default=[1],
        help="実行する条件ID(複数指定可)",
    )
    parser.add_argument(
        "--template", type=Path, default=DEFAULT_TEMPLATE_PROJECT_PATH,
        help="プリせん断テンプレートのパス",
    )
    parser.add_argument(
        "--inlet-csv", type=Path, default=None,
        help="充填結果CSV(未指定なら条件別フォルダの充填結果を使用)",
    )
    parser.add_argument(
        "--geometry", default=SHEAR_CELL_GEOMETRY_NAME,
        help="せん断セル高さを取得するGeometry名",
    )
    parser.add_argument(
        "--user-process", default=None,
        help="粒子取得対象のUser Process名(未指定なら全粒子)",
    )
    parser.add_argument(
        "--time-step", type=int, default=-1,
        help="対象時刻のインデックス(負値は末尾から、-1で最終時刻)",
    )
    parser.add_argument("--headless", action="store_true", help="Rocky GUIを表示せずに実行する")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    layout = ProjectLayout(arguments.project_id, arguments.project_root)
    condition_table_path = layout.shear_workbook
    output_root = layout.shear_test_directory

    if not ROCKY_EXECUTABLE_PATH.is_file():
        raise FileNotFoundError(f"Rocky実行ファイルが見つかりません: {ROCKY_EXECUTABLE_PATH}")
    if not arguments.template.is_file():
        raise FileNotFoundError(f"プリせん断テンプレートが見つかりません: {arguments.template}")
    if not condition_table_path.is_file():
        raise FileNotFoundError(f"条件表Excelが見つかりません: {condition_table_path}")

    for condition_id in arguments.condition_ids:
        condition = get_shear_condition(condition_table_path, condition_id)
        inlet_csv_path = arguments.inlet_csv or (
            output_root / condition.directory_name / FILLING_INLET_RELATIVE_PATH
        )

        print(
            f"[RUN] 条件{condition.condition_id}: "
            f"転がり抵抗={condition.rolling_resistance} "
            f"動摩擦={condition.dynamic_friction} "
            f"静止摩擦={condition.static_friction}"
        )
        print(f"      充填結果CSV: {inlet_csv_path}")

        client = PyRockyClient(str(ROCKY_EXECUTABLE_PATH), headless=arguments.headless)
        converted_csv_path = run_pre_shear(
            client,
            condition,
            template_project_path=arguments.template,
            inlet_csv_path=inlet_csv_path,
            output_root=output_root,
            shear_cell_geometry_name=arguments.geometry,
            user_process_name=arguments.user_process,
            time_step=arguments.time_step,
        )
        print(f"[OK] 条件{condition.condition_id}のプリせん断結果: {converted_csv_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
