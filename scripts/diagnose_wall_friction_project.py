#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""計算済みRockyプロジェクトの粒子・ジオメトリ・User Processを調査する(診断用)。

実行例:
    python scripts/diagnose_wall_friction_project.py --rocky-project <path>
"""

from __future__ import annotations

import argparse
from pathlib import Path

from poscap_calibration.rocky.client import PyRockyClient

ROCKY_EXECUTABLE_PATH = Path(r"C:\Program Files\ANSYS Inc\v252\Rocky\bin\Rocky.exe")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rocky-project", type=Path, required=True)
    parser.add_argument("--geometry", default=None, help="最大Y座標を調べるGeometry名")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    client = PyRockyClient(str(ROCKY_EXECUTABLE_PATH), headless=True)
    client.connect("127.0.0.1", 0)
    try:
        client.open_project(arguments.rocky_project)
        project = client.get_project()
        study = project.GetStudy()

        time_set = study.GetTimeSet()
        print(f"出力時刻数: {len(time_set)} / 最終時刻: {time_set[len(time_set) - 1]}")
        print(f"HasResults: {study.HasResults()}")
        print(f"SimulationDuration: {study.GetSolver().GetSimulationDuration(unit='s')}")

        print("\n--- Particles ---")
        for particle in study.GetParticleCollection():
            print(f"  {particle.GetName()}")
            for getter in ("GetCgmScaleFactor", "GetRollingResistance"):
                try:
                    print(f"    {getter}: {getattr(particle, getter)()}")
                except Exception as error:  # noqa: BLE001
                    print(f"    {getter}: 取得不可 ({type(error).__name__})")
            try:
                sizes = [
                    (point.GetSize(unit="m"), point.GetCumulativePercentage())
                    for point in particle.GetSizeDistributionList()
                ]
                print(f"    SizeDistribution: {sizes}")
            except Exception as error:  # noqa: BLE001
                print(f"    SizeDistribution: 取得不可 ({type(error).__name__})")

        print("\n--- Inlets and Outlets ---")
        for item in study.GetInletsOutletsCollection():
            name = item.GetName()
            try:
                file_path = item.GetFilePath()
            except Exception:  # noqa: BLE001
                print(f"  {name}: (Custom Inletではない)")
                continue
            # RACustomInput.GetParticleで注入先の粒子種別を確認する(ra_custom_input.pyi)。
            particle = item.GetParticle()
            particle_name = particle.GetName() if particle is not None else None
            print(f"  {name}: file={file_path} particle={particle_name}")

        print("\n--- User Processes ---")
        print(f"  {list(project.GetUserProcessCollection().GetProcessNames())}")

        print("\n--- Geometries ---")
        for geometry in study.GetGeometryCollection():
            name = geometry.GetName()
            print(f"  {name}")
            try:
                print(f"    Translation: {geometry.GetTranslation(unit='m')}")
            except Exception as error:  # noqa: BLE001
                print(f"    Translation: 取得不可 ({type(error).__name__})")

        if arguments.geometry:
            print(f"\n--- {arguments.geometry} 最終時刻の最大Y ---")
            print(client.get_geometry_max_y(arguments.geometry, -1))
    finally:
        client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
