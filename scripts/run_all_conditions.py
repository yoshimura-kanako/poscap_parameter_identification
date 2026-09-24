#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""9条件のせん断試験(充填→プリせん断→本せん断3/5/7 kPa→Excel反映)を自動実行する。

実行例:
    python scripts/run_all_conditions.py
    python scripts/run_all_conditions.py --condition-ids 1 2 3 --headless
    python scripts/run_all_conditions.py --force --stop-on-error
"""

from __future__ import annotations

import argparse
from pathlib import Path

from poscap_calibration.project_layout import ProjectLayout
from poscap_calibration.rocky.client import PyRockyClient
from poscap_calibration.run_session import start_run
from poscap_calibration.workflows.shear_batch import DEFAULT_LOADS_KPA, run_conditions

ROCKY_EXECUTABLE_PATH = Path(r"C:\Program Files\ANSYS Inc\v252\Rocky\bin\Rocky.exe")
DEFAULT_PROJECT_ID = "0"
DEFAULT_PROJECT_ROOT = Path("projects")
CONDITION_TABLE_FILENAME = "shear_analysis.xlsx"
SHEAR_CELL_GEOMETRY_NAME = "FT4_ShearCell2_5deg_mm"
TEMPLATE_DIRECTORY = Path("templates/rocky/shear")
# 手順書1.2.6で作成した充填用プロジェクト(9条件で共通の入力)。
DEFAULT_FILLING_BASE_PROJECT = (
    ProjectLayout().filling_input_directory / "work" / "Filling.rocky"
)
PRE_SHEAR_TEMPLATE_NAME = "Pre_shear.rocky"
SHEAR_TEMPLATE_BY_LOAD: dict[float, str] = {
    3.0: "Shear_3kPa.rocky",
    5.0: "Shear_5kPa.rocky",
    7.0: "Shear_7kPa.rocky",
}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument(
        "--condition-ids", type=int, nargs="+", default=None,
        help="実行する条件ID(既定は条件表の全条件)",
    )
    parser.add_argument(
        "--loads", type=float, nargs="+", default=list(DEFAULT_LOADS_KPA),
        help="実行する荷重[kPa]",
    )
    parser.add_argument("--template-dir", type=Path, default=TEMPLATE_DIRECTORY)
    parser.add_argument(
        "--filling-base-project", type=Path, default=DEFAULT_FILLING_BASE_PROJECT,
        help="手順書1.2.6で作成した充填用Rockyプロジェクト",
    )
    parser.add_argument("--geometry", default=SHEAR_CELL_GEOMETRY_NAME)
    parser.add_argument(
        "--force", action="store_true",
        help="完了済み工程も再実行する(既定は status.json を見てスキップ)",
    )
    parser.add_argument(
        "--stop-on-error", action="store_true",
        help="条件が失敗した時点で中断する(既定は次の条件へ進む)",
    )
    parser.add_argument("--skip-excel", action="store_true", help="解析Excelへ反映しない")
    parser.add_argument("--headless", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    layout = ProjectLayout(arguments.project_id, arguments.project_root)
    journal = start_run(layout.project_directory, title="フェーズ1: せん断試験9条件")
    workbook_path = layout.shear_workbook
    output_root = layout.shear_test_directory
    pre_shear_template_path = arguments.template_dir / PRE_SHEAR_TEMPLATE_NAME

    shear_templates = {
        load: arguments.template_dir / SHEAR_TEMPLATE_BY_LOAD[load]
        for load in arguments.loads
        if load in SHEAR_TEMPLATE_BY_LOAD
    }
    missing_loads = [load for load in arguments.loads if load not in SHEAR_TEMPLATE_BY_LOAD]
    if missing_loads:
        raise ValueError(
            f"テンプレート未定義の荷重が指定されました: {missing_loads}"
            f"(対応可能: {sorted(SHEAR_TEMPLATE_BY_LOAD)})"
        )

    required_paths = {
        "Rocky実行ファイル": ROCKY_EXECUTABLE_PATH,
        "解析Excel": workbook_path,
        "充填用プロジェクト": arguments.filling_base_project,
        "プリせん断テンプレート": pre_shear_template_path,
        **{f"本せん断テンプレート({load:g}kPa)": path for load, path in shear_templates.items()},
    }
    for label, path in required_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"{label}が見つかりません: {path}")

    client_factory = lambda: PyRockyClient(  # noqa: E731 - 条件ごとに新しい接続を作る
        str(ROCKY_EXECUTABLE_PATH), headless=arguments.headless
    )

    with journal.phase("phase1_shear", "フェーズ1: せん断試験"):
        batch = run_conditions(
            client_factory,
            workbook_path=workbook_path,
            filling_base_project_path=arguments.filling_base_project,
            pre_shear_template_path=pre_shear_template_path,
            shear_templates=shear_templates,
            output_root=output_root,
            shear_cell_geometry_name=arguments.geometry,
            condition_ids=tuple(arguments.condition_ids) if arguments.condition_ids else None,
            loads_kpa=tuple(arguments.loads),
            skip_completed=not arguments.force,
            update_excel=not arguments.skip_excel,
            stop_on_error=arguments.stop_on_error,
        )

    print()
    print("=" * 60)
    print(f"完了した条件: {batch['completed_condition_ids']}")
    print(f"失敗した条件: {batch['failed_condition_ids']}")
    for condition_id, result in batch["results"].items():
        if result.get("status") != "failed":
            continue
        print(f"  条件{condition_id}: {result.get('error')}")
    print(f"進捗確認: poscap status --project-id {arguments.project_id} --verbose")
    print("=" * 60)

    return 1 if batch["failed_condition_ids"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
