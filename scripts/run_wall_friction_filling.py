#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""フェーズ2の充填シミュレーションを実行する(手順書Phase2 1.2.5)。

充填はせん断試験と共通のテンプレートを使用し、フェーズ1で同定した粉体パラメータを設定する。
結果は壁面摩擦3条件で共有する。

実行例:
    python scripts/run_wall_friction_filling.py \
        --rolling-resistance 0.44427 --dynamic-friction 0.66867 --static-friction 0.73440
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from poscap_calibration.config import WALL_SECTION, get_object_name, get_template_path
from poscap_calibration.models import ShearCondition
from poscap_calibration.project_layout import DEFAULT_PROJECT_ID, ProjectLayout
from poscap_calibration.rocky.client import PyRockyClient
from poscap_calibration.workflows.wall_friction_simulation import (
    run_wall_friction_filling,
    wall_friction_fill_inlet_csv_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROCKY_EXECUTABLE_PATH = Path(r"C:\Program Files\ANSYS Inc\v252\Rocky\bin\Rocky.exe")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--project-root", type=Path, default=REPO_ROOT / "projects")
    parser.add_argument("--rolling-resistance", type=float, required=True,
                        help="フェーズ1で同定した転がり抵抗")
    parser.add_argument("--dynamic-friction", type=float, required=True,
                        help="フェーズ1で同定した粉間動摩擦係数")
    parser.add_argument("--static-friction", type=float, required=True,
                        help="フェーズ1で同定した粉間静止摩擦係数")
    parser.add_argument("--template", type=Path, default=None,
                        help="充填テンプレート(既定は設定ファイルのtemplates.wall.fill)")
    parser.add_argument("--user-process", default=None,
                        help="粒子取得対象のUser Process名(既定は設定ファイルの値)")
    parser.add_argument("--inlet-csv", type=Path, default=None,
                        help="Particle Custom Inletに設定する粒子位置CSV"
                             "(既定はフェーズ1の粒子発生結果)")
    parser.add_argument("--time-step", type=int, default=-1,
                        help="対象時刻のインデックス(-1で最終時刻)")
    parser.add_argument("--headless", action="store_true", help="Rocky GUIを表示せずに実行する")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    layout = ProjectLayout(arguments.project_id, arguments.project_root)
    output_root = layout.wall_friction_test_directory
    template = arguments.template or get_template_path(WALL_SECTION, "fill")
    user_process = arguments.user_process or get_object_name(
        WALL_SECTION, "fill_user_process"
    )
    inlet_csv = arguments.inlet_csv or (
        layout.particle_generation_results / "particle_generation_inlet.csv"
    )

    if not ROCKY_EXECUTABLE_PATH.is_file():
        raise FileNotFoundError(f"Rocky実行ファイルが見つかりません: {ROCKY_EXECUTABLE_PATH}")
    if not template.is_file():
        raise FileNotFoundError(f"充填テンプレートが見つかりません: {template}")
    if not inlet_csv.is_file():
        raise FileNotFoundError(f"粒子位置CSVが見つかりません: {inlet_csv}")

    powder_condition = ShearCondition(
        condition_id=1,
        rolling_resistance=arguments.rolling_resistance,
        dynamic_friction=arguments.dynamic_friction,
        static_friction=arguments.static_friction,
    )

    print(
        f"[RUN] 充填: 転がり抵抗={powder_condition.rolling_resistance} "
        f"粉間動摩擦={powder_condition.dynamic_friction} "
        f"粉間静止摩擦={powder_condition.static_friction}"
    )
    print(f"      テンプレート  : {template}")
    print(f"      User Process : {user_process}")
    print(f"      粒子位置CSV  : {inlet_csv}")

    client = PyRockyClient(str(ROCKY_EXECUTABLE_PATH), headless=arguments.headless)
    converted_csv_path = run_wall_friction_filling(
        client,
        powder_condition,
        template,
        output_root,
        user_process,
        inlet_csv_path=inlet_csv,
        time_step=arguments.time_step,
    )

    particle_count = len(pd.read_csv(converted_csv_path))
    print(f"[OK] 充填結果(Particle Custom Inlet): {converted_csv_path}")
    print(f"     粒子数: {particle_count}")
    print(
        "     プリせん断での既定参照先: "
        f"{wall_friction_fill_inlet_csv_path(output_root)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
