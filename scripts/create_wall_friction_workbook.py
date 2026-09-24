#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""壁面摩擦試験の条件表・解析Excelを準備する(手順書Phase2 1.2.4)。

実行例:
    python scripts/create_wall_friction_workbook.py --peak-ratio 1.0813 --steady-slope 0.22582
"""

from __future__ import annotations

import argparse
from pathlib import Path

from poscap_calibration.project_layout import DEFAULT_PROJECT_ID
from poscap_calibration.workflows.phase2_wall import (
    DEFAULT_TEMPLATE_PATH,
    create_wall_friction_analysis_workbook,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--project-root", type=Path, default=REPO_ROOT / "projects")
    parser.add_argument("--template", type=Path, default=REPO_ROOT / DEFAULT_TEMPLATE_PATH,
                        help="壁面摩擦試験用の解析Excelテンプレート")
    parser.add_argument("--peak-ratio", type=float, required=True,
                        help="壁面摩擦試験の実験ピーク比(設定・集計 B3)")
    parser.add_argument("--steady-slope", type=float, required=True,
                        help="実験定常傾き(設定・集計 B5)")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    workbook_path, conditions = create_wall_friction_analysis_workbook(
        arguments.project_id,
        arguments.peak_ratio,
        arguments.steady_slope,
        project_root=arguments.project_root,
        template_path=arguments.template,
    )

    print(f"[OK] 壁面摩擦解析Excelを作成しました: {workbook_path.resolve()}")
    print(f"     テンプレート   : {Path(arguments.template).resolve()}")
    print(f"     ピーク比(B3)   : {arguments.peak_ratio}")
    print(f"     実験定常傾き(B5): {arguments.steady_slope}")
    for condition in conditions:
        print(
            f"     条件{condition.condition_id} : "
            f"壁面動摩擦係数={condition.dynamic_friction:.6f} / "
            f"壁面静止摩擦係数={condition.static_friction:.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
