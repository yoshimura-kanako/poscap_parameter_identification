#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""充填インプットファイルを作成する(手順書1.2.6)。シミュレーションは実行しない。

実行例:
    python scripts/run_prepare_filling.py
    python scripts/run_prepare_filling.py --headless
"""

from __future__ import annotations

import argparse
from pathlib import Path

from poscap_calibration.project_layout import ProjectLayout
from poscap_calibration.rocky.client import PyRockyClient
from poscap_calibration.rocky.simulation_runner import prepare_filling_input

ROCKY_EXECUTABLE_PATH = Path(r"C:\Program Files\ANSYS Inc\v252\Rocky\bin\Rocky.exe")
TEMPLATE_PROJECT_PATH = Path("templates/rocky/shear/Filling.rocky")
_LAYOUT = ProjectLayout()
DEFAULT_RAW_CSV_PATH = (
    _LAYOUT.particle_generation_results / "particle_generation_inlet_raw.csv"
)
DEFAULT_CONVERTED_CSV_PATH = (
    _LAYOUT.particle_generation_results / "particle_generation_inlet.csv"
)
DEFAULT_WORK_PROJECT_PATH = _LAYOUT.filling_input_directory / "work" / "Filling.rocky"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-csv", type=Path, default=DEFAULT_RAW_CSV_PATH,
        help="粒子発生結果の生CSV(Cross Plot相当)のパス",
    )
    parser.add_argument(
        "--converted-csv", type=Path, default=DEFAULT_CONVERTED_CSV_PATH,
        help="Particle Custom Inlet形式(x, y, z, size)CSVの出力先パス",
    )
    parser.add_argument(
        "--work-project", type=Path, default=DEFAULT_WORK_PROJECT_PATH,
        help="テンプレートを複製して作業する.rockyファイルのパス",
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
    if not arguments.raw_csv.is_file():
        raise FileNotFoundError(f"粒子発生結果CSVが見つかりません: {arguments.raw_csv}")

    client = PyRockyClient(str(ROCKY_EXECUTABLE_PATH), headless=arguments.headless)

    work_path = prepare_filling_input(
        client,
        arguments.raw_csv,
        template_project_path=TEMPLATE_PROJECT_PATH,
        work_project_path=arguments.work_project,
        converted_csv_path=arguments.converted_csv,
    )

    print(f"[OK] Particle Custom Inlet CSVを作成しました: {arguments.converted_csv}")
    print(f"[OK] 充填インプットファイルを作成しました: {work_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
