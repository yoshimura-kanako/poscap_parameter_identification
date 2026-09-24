#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""安息角(SAOR)シミュレーションを実行する(フェーズ1)。

現時点では条件1のみを対象とし、ポスト処理と解析Excelへの結果書込みは行わない。

実行例:
    python scripts/run_saor.py
    python scripts/run_saor.py --condition-ids 1 --headless
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from poscap_calibration.condition_table import get_shear_condition
from poscap_calibration.project_layout import ProjectLayout
from poscap_calibration.rocky.client import PyRockyClient
from poscap_calibration.run_session import start_run
from poscap_calibration.workflows.phase1_saor import (
    create_saor_analysis_workbook,
    run_saor,
)

ROCKY_EXECUTABLE_PATH = Path(r"C:\Program Files\ANSYS Inc\v252\Rocky\bin\Rocky.exe")
DEFAULT_PROJECT_ID = "0"
DEFAULT_PROJECT_ROOT = Path("projects")
DEFAULT_TEMPLATE_PROJECT_PATH = Path("templates/rocky/saor/SAOR.rocky")
DEFAULT_EXCEL_TEMPLATE_PATH = Path("templates/excel/saor_analysis_template.xlsx")
DEFAULT_DISTRIBUTION_CSV = Path("input/particle_distribution/test_distribution.csv")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument(
        "--condition-ids", type=int, nargs="+", default=[1],
        help="実行する条件ID(現時点では条件1のみを想定)",
    )
    parser.add_argument(
        "--template", type=Path, default=DEFAULT_TEMPLATE_PROJECT_PATH,
        help="SAORテンプレートのパス",
    )
    parser.add_argument(
        "--excel-template", type=Path, default=DEFAULT_EXCEL_TEMPLATE_PATH,
        help="安息角解析Excelテンプレートのパス",
    )
    parser.add_argument(
        "--distribution-csv", type=Path, default=DEFAULT_DISTRIBUTION_CSV,
        help="粒度分布CSVのパス",
    )
    parser.add_argument(
        "--cgm-scale-factor", type=float, default=None,
        help="粗視化倍率(未指定ならテンプレートの値。粒子数は倍率の3乗に反比例)",
    )
    parser.add_argument(
        "--skip-post-process", action="store_true",
        help="シミュレーションのみ実行し、ポスト処理を行わない",
    )
    parser.add_argument("--headless", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    layout = ProjectLayout(arguments.project_id, arguments.project_root)
    journal = start_run(layout.project_directory, title="フェーズ1: 安息角試験")
    output_root = layout.saor_test_directory

    required_paths = {
        "Rocky実行ファイル": ROCKY_EXECUTABLE_PATH,
        "SAORテンプレート": arguments.template,
        "安息角解析Excelテンプレート": arguments.excel_template,
        "粒度分布CSV": arguments.distribution_csv,
    }
    for label, path in required_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"{label}が見つかりません: {path}")

    workbook_path = create_saor_analysis_workbook(
        arguments.excel_template, layout.saor_test_directory
    )
    print(f"[OK] 安息角解析Excel: {workbook_path}")

    with journal.phase("phase1_saor", "フェーズ1: 安息角試験"):
        total = len(arguments.condition_ids)
        for index, condition_id in enumerate(arguments.condition_ids, start=1):
            condition = get_shear_condition(workbook_path, condition_id)
            with journal.step(
                f"condition_{condition_id:02d}",
                f"安息角 条件{condition_id}",
                index=index,
                total=total,
            ):
                journal.progress(
                    f"条件{condition.condition_id}: 転がり抵抗={condition.rolling_resistance} "
                    f"動摩擦={condition.dynamic_friction} 静止摩擦={condition.static_friction}"
                )

                client = PyRockyClient(
                    str(ROCKY_EXECUTABLE_PATH), headless=arguments.headless
                )
                project_path = run_saor(
                    client,
                    condition,
                    template_project_path=arguments.template,
                    distribution_csv_path=arguments.distribution_csv,
                    output_root=output_root,
                    cgm_scale_factor=arguments.cgm_scale_factor,
                    post_process=not arguments.skip_post_process,
                )
                print(
                    f"[OK] 条件{condition.condition_id}の安息角シミュレーション: {project_path}"
                )

                if not arguments.skip_post_process:
                    status = json.loads(
                        (project_path.parents[1] / "status.json").read_text(encoding="utf-8")
                    )
                    result = status.get("post_process_result", {})
                    print(f"     山頂側安息角: {result.get('saor_from_top_deg')}")
                    print(f"     裾側安息角  : {result.get('saor_from_bottom_deg')}")
                    print(f"     出力先      : {result.get('output_directory')}")
                    journal.record_result(
                        f"saor_condition_{condition_id:02d}",
                        {
                            "saor_from_top_deg": result.get("saor_from_top_deg"),
                            "saor_from_bottom_deg": result.get("saor_from_bottom_deg"),
                        },
                        output_directory=result.get("output_directory"),
                    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
