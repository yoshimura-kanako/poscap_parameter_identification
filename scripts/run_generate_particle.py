#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""粒子発生シミュレーションを実行し、Cross Plot <04>をCSV出力する(FR-07)。

実行例:
    python scripts/run_generate_particle.py
    python scripts/run_generate_particle.py --headless
"""

from __future__ import annotations

import argparse
from pathlib import Path

from poscap_calibration.project_layout import ProjectLayout
from poscap_calibration.rocky.client import PyRockyClient
from poscap_calibration.rocky.simulation_runner import run_particle_generation

ROCKY_EXECUTABLE_PATH = Path(r"C:\Program Files\ANSYS Inc\v252\Rocky\bin\Rocky.exe")
TEMPLATE_PROJECT_PATH = Path("templates/rocky/shear/Generate_Particle.rocky")
DEFAULT_DISTRIBUTION_CSV = Path("input/particle_distribution/test_distribution.csv")
_LAYOUT = ProjectLayout()
DEFAULT_WORK_PROJECT_PATH = _LAYOUT.particle_generation_work / "Generate_Particle.rocky"
DEFAULT_OUTPUT_CSV_PATH = (
    _LAYOUT.particle_generation_results / "particle_generation_inlet_raw.csv"
)
# Cross Plot <04>が参照しているUser Process(docs/Rocky.md 5.4節)。
USER_PROCESS_NAME = "First_20deg"
# 対象時刻は0秒(最初の出力時刻)。
TARGET_TIME_STEP = 0


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--distribution-csv", type=Path, default=DEFAULT_DISTRIBUTION_CSV,
        help="粒度分布CSV(particle_size, cumulative_mass_percent)のパス",
    )
    parser.add_argument(
        "--work-project", type=Path, default=DEFAULT_WORK_PROJECT_PATH,
        help="テンプレートを複製して作業する.rockyファイルのパス",
    )
    parser.add_argument(
        "--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV_PATH,
        help="粒子データの出力先CSVパス",
    )
    parser.add_argument(
        "--user-process", default=USER_PROCESS_NAME,
        help="取得対象のUser Process名",
    )
    parser.add_argument(
        "--time-step", type=int, default=TARGET_TIME_STEP,
        help="対象時刻のインデックス(負値は末尾から、-1で最終時刻)",
    )
    parser.add_argument(
        "--headless", action="store_true", help="Rocky GUIを表示せずに実行する",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    if not TEMPLATE_PROJECT_PATH.is_file():
        raise FileNotFoundError(f"Rockyプロジェクトが見つかりません: {TEMPLATE_PROJECT_PATH}")
    if not ROCKY_EXECUTABLE_PATH.is_file():
        raise FileNotFoundError(f"Rocky実行ファイルが見つかりません: {ROCKY_EXECUTABLE_PATH}")

    client = PyRockyClient(str(ROCKY_EXECUTABLE_PATH), headless=arguments.headless)

    output_path = run_particle_generation(
        client,
        arguments.distribution_csv,
        template_project_path=TEMPLATE_PROJECT_PATH,
        work_project_path=arguments.work_project,
        user_process_name=arguments.user_process,
        output_csv_path=arguments.output_csv,
        time_step=arguments.time_step,
    )

    print(f"[OK] 粒子データ({arguments.user_process})を出力しました: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
