#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""安息角の実験データ点を解析Excelへ転記し、再計算して安息角を取得する。

実行例:
    python scripts/import_saor_points.py --condition-ids 1
    python scripts/import_saor_points.py                    # 全条件(1〜9)
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from poscap_calibration.project_layout import ProjectLayout
from poscap_calibration.saor_analysis_excel import (
    SaorAnalysisExcelError,
    get_condition_sheet_name,
    recalculate_and_read_angles,
    write_experiment_points,
)
from poscap_calibration.workflows.phase1_saor import POST_PROCESS_RELATIVE_PATH

DEFAULT_PROJECT_ID = "0"
DEFAULT_PROJECT_ROOT = Path("projects")
EXPERIMENT_POINTS_FILENAME = "experiment_data_points.csv"
SUMMARY_FILENAME = "saor_excel_summary.json"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument(
        "--condition-ids", type=int, nargs="+", default=list(range(1, 10)),
        help="転記する条件ID(既定は1〜9)",
    )
    parser.add_argument(
        "--csv-filename", default=EXPERIMENT_POINTS_FILENAME,
        help="転記元CSVのファイル名(条件別のResults/saor配下)",
    )
    parser.add_argument(
        "--skip-missing", action="store_true",
        help="実験データ点CSVが無い条件をエラーにせずスキップする",
    )
    parser.add_argument(
        "--no-recalculate", action="store_true",
        help="Excelの再計算と安息角の取得を行わない",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    arguments = parse_arguments()

    layout = ProjectLayout(arguments.project_id, arguments.project_root)
    workbook_path = layout.saor_workbook

    if not workbook_path.is_file():
        raise FileNotFoundError(f"安息角解析Excelが見つかりません: {workbook_path}")

    written: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    sheet_names_by_condition: dict[int, str] = {}

    for condition_id in arguments.condition_ids:
        csv_path = (
            layout.saor_condition_directory(condition_id)
            / POST_PROCESS_RELATIVE_PATH
            / arguments.csv_filename
        )
        if not csv_path.is_file():
            message = f"条件{condition_id}: 実験データ点CSVが見つかりません: {csv_path}"
            if arguments.skip_missing:
                print(f"[SKIP] {message}")
                skipped.append({"condition_id": condition_id, "reason": str(csv_path)})
                continue
            raise FileNotFoundError(
                f"{message}。先に scripts/run_saor.py を実行するか "
                "--skip-missing を指定してください。"
            )

        try:
            result = write_experiment_points(workbook_path, condition_id, csv_path)
        except SaorAnalysisExcelError as error:
            raise SaorAnalysisExcelError(f"条件{condition_id}の転記に失敗しました: {error}")

        sheet_names_by_condition[condition_id] = result["sheet_name"]
        written.append(result)
        print(
            f"[OK] 条件{condition_id}: シート '{result['sheet_name']}' へ "
            f"{result['row_count']}行を転記しました"
        )

    summary: dict[str, object] = {
        "workbook": str(workbook_path.resolve()),
        "written": written,
        "skipped": skipped,
    }

    if written and not arguments.no_recalculate:
        print("[RUN] Excelを再計算しています...")
        summary["excel"] = recalculate_and_read_angles(
            workbook_path, sheet_names_by_condition
        )
        angles = summary["excel"].get("angles_deg", {})
        for condition_id, angle in sorted(angles.items(), key=lambda item: int(item[0])):
            print(f"     条件{condition_id}の安息角: {angle}")
        if summary["excel"].get("formula_errors"):
            print(f"     [警告] 数式エラー: {summary['excel']['formula_errors']}")

    summary_path = layout.saor_test_directory / SUMMARY_FILENAME
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] サマリを保存しました: {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
