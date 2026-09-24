#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""計算済みの充填プロジェクトから粒子を取得しParticle Custom Inlet CSVを作成する。

シミュレーションは実行せず、後処理のみを行う。

実行例:
    python scripts/export_wall_friction_fill_particles.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from poscap_calibration.config import WALL_SECTION, get_object_name
from poscap_calibration.models import ShearCondition
from poscap_calibration.project_layout import DEFAULT_PROJECT_ID, ProjectLayout
from poscap_calibration.rocky.client import PyRockyClient
from poscap_calibration.workflows.wall_friction_simulation import (
    export_wall_friction_fill_particles,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROCKY_EXECUTABLE_PATH = Path(r"C:\Program Files\ANSYS Inc\v252\Rocky\bin\Rocky.exe")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--project-root", type=Path, default=REPO_ROOT / "projects")
    parser.add_argument("--rocky-project", type=Path, default=None,
                        help="計算済みの充填プロジェクト(.rocky)")
    parser.add_argument("--user-process", default=None,
                        help="粒子取得対象のUser Process名(既定は設定ファイルの値)")
    parser.add_argument("--time-step", type=int, default=-1,
                        help="対象時刻のインデックス(-1で最終時刻)")
    parser.add_argument("--headless", action="store_true", help="Rocky GUIを表示せずに実行する")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    layout = ProjectLayout(arguments.project_id, arguments.project_root)
    output_root = layout.wall_friction_test_directory
    # 充填は粉体パラメータのみに依存するため、条件IDは後処理APIの互換引数にのみ使う。
    powder_condition = ShearCondition(
        condition_id=1, rolling_resistance=0.0, dynamic_friction=0.0, static_friction=0.0
    )
    user_process = arguments.user_process or get_object_name(
        WALL_SECTION, "fill_user_process"
    )
    rocky_project = arguments.rocky_project or (
        output_root
        / "fill"
        / "project"
        / "Filling.rocky"
    )

    if not ROCKY_EXECUTABLE_PATH.is_file():
        raise FileNotFoundError(f"Rocky実行ファイルが見つかりません: {ROCKY_EXECUTABLE_PATH}")

    print(f"[RUN] 充填結果の後処理: {rocky_project}")
    print(f"      User Process : {user_process}")

    client = PyRockyClient(str(ROCKY_EXECUTABLE_PATH), headless=arguments.headless)
    converted_csv_path = export_wall_friction_fill_particles(
        client,
        rocky_project,
        output_root,
        powder_condition,
        user_process,
        time_step=arguments.time_step,
    )

    converted = pd.read_csv(converted_csv_path)
    print(f"[OK] Particle Custom Inlet CSV: {converted_csv_path}")
    print(f"     粒子数: {len(converted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
