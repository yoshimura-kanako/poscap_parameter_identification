#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""安息角シミュレーション完了後のポスト処理を実行する。

Rocky同梱マクロ "Pana - Calibration 1: SAOR v242" と同じ処理をPyRocky経由で実行し、
角度・データ点・図を条件別フォルダへ出力する。

実行例:
    python scripts/run_saor_post_process.py
    python scripts/run_saor_post_process.py --condition-ids 1
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from poscap_calibration.project_layout import ProjectLayout
from poscap_calibration.rocky.client import PyRockyClient
from poscap_calibration.workflows.saor_post_process import (
    DEFAULT_SCRIPT_PATH,
    run_saor_post_process,
)

ROCKY_EXECUTABLE_PATH = Path(r"C:\Program Files\ANSYS Inc\v252\Rocky\bin\Rocky.exe")
DEFAULT_PROJECT_ID = "0"
DEFAULT_PROJECT_ROOT = Path("projects")
PROJECT_FILENAME = "SAOR.rocky"
# 元スクリプトの慣例に合わせ、条件フォルダ配下の Results/saor/ へ出力する。
OUTPUT_RELATIVE_PATH = Path("Results") / "saor"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--condition-ids", type=int, nargs="+", default=[1])
    parser.add_argument(
        "--script", type=Path, default=DEFAULT_SCRIPT_PATH,
        help="ポスト処理スクリプトのパス",
    )
    parser.add_argument("--headless", action="store_true")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    arguments = parse_arguments()

    layout = ProjectLayout(arguments.project_id, arguments.project_root)

    if not ROCKY_EXECUTABLE_PATH.is_file():
        raise FileNotFoundError(f"Rocky実行ファイルが見つかりません: {ROCKY_EXECUTABLE_PATH}")
    if not arguments.script.is_file():
        raise FileNotFoundError(f"ポスト処理スクリプトが見つかりません: {arguments.script}")

    for condition_id in arguments.condition_ids:
        condition_directory = layout.saor_condition_directory(condition_id)
        project_path = condition_directory / "project" / PROJECT_FILENAME
        output_directory = condition_directory / OUTPUT_RELATIVE_PATH

        if not project_path.is_file():
            raise FileNotFoundError(
                f"条件{condition_id}: 安息角プロジェクトが見つかりません: {project_path}。"
                "先に scripts/run_saor.py を実行してください。"
            )

        print(f"[RUN] 条件{condition_id}: {project_path}")

        client = PyRockyClient(str(ROCKY_EXECUTABLE_PATH), headless=arguments.headless)
        client.connect("127.0.0.1", 0)
        try:
            client.open_project(project_path)
            result = run_saor_post_process(
                client.get_project(), output_directory, script_path=arguments.script
            )
        finally:
            client.disconnect()

        summary_path = condition_directory / "saor_post_process.json"
        summary_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

        print(f"[OK] 条件{condition_id}の安息角:")
        print(f"     山頂側 : {result['saor_from_top_deg']:.2f} 度")
        print(f"     裾側   : {result['saor_from_bottom_deg']:.2f} 度")
        print(f"     出力先 : {result['output_directory']}")
        for name in result["outputs"]:
            print(f"       - {name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
