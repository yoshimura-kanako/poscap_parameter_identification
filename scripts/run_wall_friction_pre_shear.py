#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""フェーズ2のプリせん断シミュレーションを実行する(手順書Phase2 1.2.6)。

壁面摩擦条件は解析Excelの条件表から取得する。条件2・3も``--condition-ids``で指定できる。

実行例:
    python scripts/run_wall_friction_pre_shear.py --condition-ids 1 \
        --rolling-resistance 0.44427 --dynamic-friction 0.66867 --static-friction 0.73440
"""

from __future__ import annotations

import argparse
from pathlib import Path

from poscap_calibration.config import WALL_SECTION, get_object_name, get_template_path
from poscap_calibration.models import ShearCondition
from poscap_calibration.project_layout import DEFAULT_PROJECT_ID, ProjectLayout
from poscap_calibration.rocky.client import PyRockyClient
from poscap_calibration.wall_friction_analysis_excel import (
    read_wall_friction_conditions,
)
from poscap_calibration.workflows.wall_friction_simulation import (
    run_wall_friction_pre_shear,
    wall_friction_fill_inlet_csv_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROCKY_EXECUTABLE_PATH = Path(r"C:\Program Files\ANSYS Inc\v252\Rocky\bin\Rocky.exe")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--project-root", type=Path, default=REPO_ROOT / "projects")
    parser.add_argument("--condition-ids", type=int, nargs="+", default=[1],
                        help="実行する壁面摩擦条件ID(複数指定可)")
    parser.add_argument("--rolling-resistance", type=float, required=True,
                        help="フェーズ1で同定した転がり抵抗")
    parser.add_argument("--dynamic-friction", type=float, required=True,
                        help="フェーズ1で同定した粉間動摩擦係数")
    parser.add_argument("--static-friction", type=float, required=True,
                        help="フェーズ1で同定した粉間静止摩擦係数")
    parser.add_argument("--workbook", type=Path, default=None,
                        help="壁面摩擦条件表Excel(既定はwall_friction_test/wall_friction_analysis.xlsx)")
    parser.add_argument("--template", type=Path, default=None,
                        help="プリせん断テンプレート(既定は設定ファイルのtemplates.wall.pre_shear)")
    parser.add_argument("--inlet-csv", type=Path, default=None,
                        help="充填結果CSV(未指定なら共有充填結果を使用)")
    parser.add_argument("--geometry", default=None,
                        help="ディスク高さを取得するGeometry名(既定は設定ファイルの値)")
    parser.add_argument("--wall-material", default=None,
                        help="壁面材料名(未指定ならGeometryの材料を使用)")
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
    workbook_path = arguments.workbook or layout.wall_friction_workbook
    template = arguments.template or get_template_path(WALL_SECTION, "pre_shear")
    geometry_name = arguments.geometry or get_object_name(
        WALL_SECTION, "wall_disc_geometry"
    )
    wall_material = arguments.wall_material or get_object_name(
        WALL_SECTION, "wall_material"
    )
    user_process = arguments.user_process or get_object_name(
        WALL_SECTION, "pre_user_process"
    )

    if not ROCKY_EXECUTABLE_PATH.is_file():
        raise FileNotFoundError(f"Rocky実行ファイルが見つかりません: {ROCKY_EXECUTABLE_PATH}")
    if not template.is_file():
        raise FileNotFoundError(f"プリせん断テンプレートが見つかりません: {template}")
    if not workbook_path.is_file():
        raise FileNotFoundError(f"壁面摩擦条件表Excelが見つかりません: {workbook_path}")

    powder_condition = ShearCondition(
        condition_id=1,
        rolling_resistance=arguments.rolling_resistance,
        dynamic_friction=arguments.dynamic_friction,
        static_friction=arguments.static_friction,
    )
    inlet_csv_path = arguments.inlet_csv or wall_friction_fill_inlet_csv_path(output_root)

    conditions = {
        condition.condition_id: condition
        for condition in read_wall_friction_conditions(workbook_path)
    }
    for condition_id in arguments.condition_ids:
        if condition_id not in conditions:
            raise KeyError(
                f"条件{condition_id}が条件表にありません。利用可能: {sorted(conditions)}"
            )

    for condition_id in arguments.condition_ids:
        wall_condition = conditions[condition_id]
        print(
            f"[RUN] 壁面摩擦条件{wall_condition.condition_id}: "
            f"壁面動摩擦={wall_condition.dynamic_friction} "
            f"壁面静止摩擦={wall_condition.static_friction}"
        )
        print(f"      充填結果CSV : {inlet_csv_path}")
        print(f"      Geometry    : {geometry_name}")

        client = PyRockyClient(str(ROCKY_EXECUTABLE_PATH), headless=arguments.headless)
        result = run_wall_friction_pre_shear(
            client,
            powder_condition,
            wall_condition,
            template_project_path=template,
            inlet_csv_path=inlet_csv_path,
            output_root=output_root,
            disc_geometry_name=geometry_name,
            wall_material_name=wall_material,
            user_process_name=user_process,
            time_step=arguments.time_step,
            project_filename=template.name,
        )

        height = result["disc_height"]
        print(
            f"[OK] 条件{wall_condition.condition_id}: "
            f"ディスク高さ={height['maximum_y_m']}{height['unit']} "
            f"(時刻={height['time_s']}s) 粒子数={result['particle_count']}"
        )
        print(f"     粒子CSV       : {result['converted_csv']}")
        print(f"     ディスク高さ   : {result['disc_height_json']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
