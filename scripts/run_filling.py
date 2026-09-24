#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""条件別の充填シミュレーションを実行する(手順書1.2.7)。

実行例:
    python scripts/run_filling.py --condition-ids 1
    python scripts/run_filling.py --condition-ids 1 2 3 --headless
"""

from __future__ import annotations

import argparse
from pathlib import Path

from poscap_calibration.condition_table import get_shear_condition
from poscap_calibration.project_layout import ProjectLayout
from poscap_calibration.rocky.client import PyRockyClient
from poscap_calibration.rocky.simulation_runner import run_filling

ROCKY_EXECUTABLE_PATH = Path(r"C:\Program Files\ANSYS Inc\v252\Rocky\bin\Rocky.exe")
DEFAULT_PROJECT_ID = "0"
DEFAULT_PROJECT_ROOT = Path("projects")
DEFAULT_BASE_PROJECT_PATH = (
    ProjectLayout().filling_input_directory / "work" / "Filling.rocky"
)
CONDITION_TABLE_FILENAME = "shear_analysis.xlsx"
# docs/Rocky.md 7.5節の充填工程のUser Process。
FILL_USER_PROCESS_NAME = "Split"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-id", default=DEFAULT_PROJECT_ID,
        help="条件表と結果を格納するプロジェクトID",
    )
    parser.add_argument(
        "--project-root", type=Path, default=DEFAULT_PROJECT_ROOT,
        help="プロジェクトフォルダの親ディレクトリ",
    )
    parser.add_argument(
        "--condition-ids", type=int, nargs="+", default=[1],
        help="実行する条件ID(複数指定可、将来1〜9をまとめて実行できる)",
    )
    parser.add_argument(
        "--base-project", type=Path, default=DEFAULT_BASE_PROJECT_PATH,
        help="手順書1.2.6で作成した充填用Rockyプロジェクトのパス",
    )
    parser.add_argument(
        "--user-process", default=FILL_USER_PROCESS_NAME,
        help="充填結果を取得するUser Process名",
    )
    parser.add_argument(
        "--time-step", type=int, default=-1,
        help="対象時刻のインデックス(負値は末尾から、-1で最終時刻)",
    )
    parser.add_argument(
        "--headless", action="store_true", help="Rocky GUIを表示せずに実行する",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    layout = ProjectLayout(arguments.project_id, arguments.project_root)
    condition_table_path = layout.shear_workbook
    output_root = layout.shear_test_directory
    if not ROCKY_EXECUTABLE_PATH.is_file():
        raise FileNotFoundError(f"Rocky実行ファイルが見つかりません: {ROCKY_EXECUTABLE_PATH}")
    if not condition_table_path.is_file():
        raise FileNotFoundError(f"条件表Excelが見つかりません: {condition_table_path}")
    if not arguments.base_project.is_file():
        raise FileNotFoundError(
            f"充填用Rockyプロジェクトが見つかりません: {arguments.base_project}"
        )

    for condition_id in arguments.condition_ids:
        condition = get_shear_condition(condition_table_path, condition_id)
        print(
            f"[RUN] 条件{condition.condition_id}: "
            f"転がり抵抗={condition.rolling_resistance} "
            f"動摩擦={condition.dynamic_friction} "
            f"静止摩擦={condition.static_friction}"
        )

        client = PyRockyClient(str(ROCKY_EXECUTABLE_PATH), headless=arguments.headless)
        converted_csv_path = run_filling(
            client,
            condition,
            base_project_path=arguments.base_project,
            output_root=output_root,
            user_process_name=arguments.user_process,
            time_step=arguments.time_step,
        )
        print(f"[OK] 条件{condition.condition_id}の充填結果: {converted_csv_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
