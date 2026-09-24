#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""応答曲面用データを解析Excelの「csv出力用」シートから出力する(手順書1.2.8)。

9条件すべての解析が完了した後に1回だけ実行する。

実行例:
    python scripts/export_response_surface.py
    python scripts/export_response_surface.py --workbook projects/0/shear_test/shear_analysis_test.xlsx
"""

from __future__ import annotations

import argparse
from pathlib import Path

from poscap_calibration.project_layout import ProjectLayout
from poscap_calibration.response_surface_export import export_response_surface_data

DEFAULT_PROJECT_ID = "0"
DEFAULT_PROJECT_ROOT = Path("projects")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument(
        "--workbook", type=Path, default=None,
        help="解析Excel(既定はshear_test/shear_analysis.xlsx)",
    )
    parser.add_argument(
        "--output-csv", type=Path, default=None,
        help="出力先CSV(既定はshear_test/shear_response_surface_data.csv)",
    )
    parser.add_argument(
        "--no-recalculate", action="store_true",
        help="Excelの再計算と保存を行わない",
    )
    parser.add_argument(
        "--allow-incomplete", action="store_true",
        help="数式エラーが残っていても出力する(未完了条件がある場合)",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    layout = ProjectLayout(arguments.project_id, arguments.project_root)
    workbook_path = arguments.workbook or layout.shear_workbook
    output_csv_path = arguments.output_csv or (
        workbook_path.parent / layout.shear_response_surface_csv.name
    )

    if not workbook_path.is_file():
        raise FileNotFoundError(f"解析Excelが見つかりません: {workbook_path}")

    result = export_response_surface_data(
        workbook_path,
        output_csv_path,
        recalculate=not arguments.no_recalculate,
        allow_incomplete=arguments.allow_incomplete,
    )

    print(f"[OK] 応答曲面用データを出力しました: {result['output_csv']}")
    print(f"     解析Excel : {result['workbook']}")
    print(f"     シート     : {result['sheet']}")
    print(f"     行数       : {result['row_count']}(見出し含む、データ{result['data_row_count']}行)")
    print(f"     列数       : {result['column_count']}")
    print(f"     再計算     : {'実行済み' if result['recalculated'] else '未実行'}")
    if result.get("formula_errors"):
        print(f"     [警告] 数式エラー: {result['formula_errors'][:5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
