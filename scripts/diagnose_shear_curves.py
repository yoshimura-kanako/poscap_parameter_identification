#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""本せん断プロジェクトのTime Plot参照元(Force Y / Moment Y)を特定する(読み取り専用、一時スクリプト)。

実行例:
    python scripts/diagnose_shear_curves.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from poscap_calibration.rocky.client import PyRockyClient

ROCKY_EXECUTABLE_PATH = Path(r"C:\Program Files\ANSYS Inc\v252\Rocky\bin\Rocky.exe")
DEFAULT_PROJECT_PATH = Path("templates/rocky/shear/Shear_3kPa.rocky")
TARGET_CURVE_KEYWORDS = ("force y", "moment y")
SHEAR_CELL_GEOMETRY_NAME = "FT4_ShearCell2_5deg_mm"


def probe(label: str, function: Callable[[], Any]) -> Any:
    try:
        result = function()
    except Exception as error:  # noqa: BLE001 - リモートAPIの例外種別が確定していないため
        print(f"  [NG] {label}: {type(error).__name__}: {error}")
        return None
    print(f"  [OK] {label}: {result!r}")
    return result


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT_PATH)
    parser.add_argument("--geometry", default=SHEAR_CELL_GEOMETRY_NAME)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    if not arguments.project.is_file():
        raise FileNotFoundError(f"プロジェクトが見つかりません: {arguments.project}")

    client = PyRockyClient(str(ROCKY_EXECUTABLE_PATH), headless=True)
    client.connect("127.0.0.1", 0)
    try:
        client.open_project(arguments.project)
        study = client._study
        project = client._project

        print("=" * 70)
        print("0. 基本情報")
        print("=" * 70)
        probe("HasResults", study.HasResults)
        probe("GetSolver().GetSimulationDuration", lambda: study.GetSolver().GetSimulationDuration(unit="s"))
        probe("GetSolver().GetSimulationTarget", lambda: study.GetSolver().GetSimulationTarget())

        print()
        print("=" * 70)
        print("1. せん断セルGeometryのTranslation")
        print("=" * 70)
        geometry = probe(
            f"study.GetGeometry({arguments.geometry!r})",
            lambda: study.GetGeometry(arguments.geometry),
        )
        if geometry is not None:
            probe("geometry.GetTranslation(unit='m')", lambda: geometry.GetTranslation(unit="m"))
            probe("geometry.GetTranslation()", geometry.GetTranslation)

        print()
        print("=" * 70)
        print("2. Study要素の一覧")
        print("=" * 70)
        element_names = probe("study.GetElementNames()", study.GetElementNames) or []

        print()
        print("=" * 70)
        print("3. Force Y / Moment Y を持つ要素の探索")
        print("=" * 70)
        matched: list[tuple[str, list[str]]] = []
        for element_name in element_names:
            try:
                element = study.GetElement(element_name, raise_if_no_found=False)
                if element is None:
                    continue
                curve_names = list(element.GetCurveNames())
            except Exception as error:  # noqa: BLE001
                if "motion" in str(element_name).lower():
                    print(f"  [NG] {element_name}.GetCurveNames(): {type(error).__name__}: {error}")
                continue
            if "motion" in str(element_name).lower():
                print(f"  [--] {element_name} の全カーブ: {curve_names}")
            hits = [
                curve
                for curve in curve_names
                if any(keyword in str(curve).lower() for keyword in TARGET_CURVE_KEYWORDS)
            ]
            if hits:
                matched.append((element_name, curve_names))
                print(f"  [HIT] {element_name}")
                print(f"        該当カーブ: {hits}")

        if not matched:
            print("  Force Y / Moment Y を持つ要素が見つかりませんでした。")

        print()
        print("=" * 70)
        print("4. Motion Frames配下の探索")
        print("=" * 70)
        motion_source = probe("study.GetMotionFrameSource()", study.GetMotionFrameSource)
        if motion_source is not None:
            for accessor in ("GetCurveNames", "GetChildren", "GetMotionFrames", "GetFrames"):
                probe(f"motion_source.{accessor}()", getattr(motion_source, accessor))

        print()
        print("=" * 70)
        print("5. GetNumpyCurveの動作確認")
        print("=" * 70)
        for element_name, curve_names in matched:
            element = study.GetElement(element_name, raise_if_no_found=False)
            for curve in curve_names:
                if not any(k in str(curve).lower() for k in TARGET_CURVE_KEYWORDS):
                    continue
                result = probe(
                    f"{element_name} / GetNumpyCurve({curve!r})",
                    lambda e=element, c=curve: e.GetNumpyCurve(c),
                )
                if result is not None:
                    try:
                        x_values, y_values = result
                        print(f"        x長さ={len(x_values)} y長さ={len(y_values)}")
                        print(f"        x先頭5={list(x_values[:5])}")
                        print(f"        y先頭5={list(y_values[:5])}")
                    except Exception as error:  # noqa: BLE001
                        print(f"        戻り値の展開に失敗: {type(error).__name__}: {error}")

        print()
        print("=" * 70)
        print("6. User Process一覧(参考)")
        print("=" * 70)
        collection = probe("project.GetUserProcessCollection()", project.GetUserProcessCollection)
        if collection is not None:
            probe("collection.GetProcessNames()", collection.GetProcessNames)
    finally:
        client.disconnect()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
