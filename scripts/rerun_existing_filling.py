#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""既存のRockyプロジェクトを複製せず直接開いて充填シミュレーションを再実行する。

`run_filling`はテンプレートを複製してから実行する設計のため、
既存の計算済みプロジェクトをそのまま再計算したい場合には使えない。
本スクリプトは指定した``.rocky``を直接開き、結果削除→再計算→完了確認のみを行う。

実行例:
    python scripts/rerun_existing_filling.py `
        --project "C:\...\wall_friction_test\fill\project\Filling.rocky"
"""

from __future__ import annotations

import argparse
from pathlib import Path

from poscap_calibration.rocky.client import PyRockyClient

ROCKY_EXECUTABLE_PATH = Path(r"C:\Program Files\ANSYS Inc\v252\Rocky\bin\Rocky.exe")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True, help="再実行する.rockyファイル")
    parser.add_argument("--headless", action="store_true", help="Rocky GUIを表示せずに実行する")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    if not ROCKY_EXECUTABLE_PATH.is_file():
        raise FileNotFoundError(f"Rocky実行ファイルが見つかりません: {ROCKY_EXECUTABLE_PATH}")
    if not arguments.project.is_file():
        raise FileNotFoundError(f"Rockyプロジェクトが見つかりません: {arguments.project}")

    client = PyRockyClient(str(ROCKY_EXECUTABLE_PATH), headless=arguments.headless)
    client.connect("127.0.0.1", 0)
    try:
        print(f"[RUN] プロジェクトを開いています: {arguments.project}")
        client.open_project(arguments.project)
        client.delete_results()
        print("[RUN] シミュレーションを再実行中...")
        client.run_simulation()
        if not client.is_completed():
            raise RuntimeError("充填シミュレーションが正常終了しませんでした。")
        print("[OK] シミュレーションが完了しました。")
    finally:
        client.disconnect()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
