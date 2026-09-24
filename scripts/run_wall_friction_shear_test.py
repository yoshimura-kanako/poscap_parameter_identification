#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""フェーズ2の本せん断シミュレーションと解析Excel反映を行う(手順書Phase2 1.2.7)。

荷重・条件は引数で受け取るため、3/5/7 kPaと条件1〜3へそのまま展開できる。

実行例:
    python scripts/run_wall_friction_shear_test.py --condition-ids 1 --loads 3 \
        --rolling-resistance 0.44427 --dynamic-friction 0.66867 --static-friction 0.73440
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from poscap_calibration.config import WALL_SECTION, get_object_name, get_template_path
from poscap_calibration.models import ShearCondition
from poscap_calibration.project_layout import DEFAULT_PROJECT_ID, ProjectLayout
from poscap_calibration.rocky.client import PyRockyClient
from poscap_calibration.rocky.simulation_runner import read_shear_time_series
from poscap_calibration.run_session import start_run
from poscap_calibration.wall_friction_analysis_excel import (
    SHEAR_SHEET_HEADERS,
    read_wall_friction_conditions,
    update_shear_time_series,
)
from poscap_calibration.workflows.wall_friction_simulation import (
    PRE_SHEAR_HEIGHT_RELATIVE_PATH,
    PRE_SHEAR_INLET_RELATIVE_PATH,
    run_wall_friction_shear_test,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROCKY_EXECUTABLE_PATH = Path(r"C:\Program Files\ANSYS Inc\v252\Rocky\bin\Rocky.exe")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--project-root", type=Path, default=REPO_ROOT / "projects")
    parser.add_argument("--condition-ids", type=int, nargs="+", default=[1],
                        help="実行する壁面摩擦条件ID(複数指定可)")
    parser.add_argument("--loads", type=float, nargs="+", default=[3.0],
                        help=f"実行する荷重kPa(対応: {sorted(SHEAR_SHEET_HEADERS)})")
    parser.add_argument("--rolling-resistance", type=float, required=True,
                        help="フェーズ1で同定した転がり抵抗")
    parser.add_argument("--dynamic-friction", type=float, required=True,
                        help="フェーズ1で同定した粉間動摩擦係数")
    parser.add_argument("--static-friction", type=float, required=True,
                        help="フェーズ1で同定した粉間静止摩擦係数")
    parser.add_argument("--workbook", type=Path, default=None,
                        help="壁面摩擦解析Excel(既定はwall_friction_test/wall_friction_analysis.xlsx)")
    parser.add_argument("--geometry", default=None,
                        help="ディスクのGeometry名(既定は設定ファイルの値)")
    parser.add_argument("--wall-material", default=None,
                        help="壁面材料名(未指定ならGeometryの材料を使用)")
    parser.add_argument("--skip-excel", action="store_true",
                        help="Excelへの貼付け・再計算を行わない")
    parser.add_argument("--headless", action="store_true", help="Rocky GUIを表示せずに実行する")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    layout = ProjectLayout(arguments.project_id, arguments.project_root)
    journal = start_run(layout.project_directory, title="フェーズ2: 壁面摩擦本せん断")
    output_root = layout.wall_friction_test_directory
    workbook_path = arguments.workbook or layout.wall_friction_workbook
    geometry_name = arguments.geometry or get_object_name(
        WALL_SECTION, "wall_disc_geometry"
    )
    wall_material = arguments.wall_material or get_object_name(WALL_SECTION, "wall_material")
    time_plot_name = get_object_name(WALL_SECTION, "torque_plot")

    if not ROCKY_EXECUTABLE_PATH.is_file():
        raise FileNotFoundError(f"Rocky実行ファイルが見つかりません: {ROCKY_EXECUTABLE_PATH}")
    if not workbook_path.is_file():
        raise FileNotFoundError(f"壁面摩擦解析Excelが見つかりません: {workbook_path}")

    powder_condition = ShearCondition(
        condition_id=1,
        rolling_resistance=arguments.rolling_resistance,
        dynamic_friction=arguments.dynamic_friction,
        static_friction=arguments.static_friction,
    )

    conditions = {
        condition.condition_id: condition
        for condition in read_wall_friction_conditions(workbook_path)
    }
    for condition_id in arguments.condition_ids:
        if condition_id not in conditions:
            raise KeyError(
                f"条件{condition_id}が条件表にありません。利用可能: {sorted(conditions)}"
            )
    for load_kpa in arguments.loads:
        if float(load_kpa) not in SHEAR_SHEET_HEADERS:
            raise KeyError(
                f"未対応の荷重です: {load_kpa}kPa。対応: {sorted(SHEAR_SHEET_HEADERS)}"
            )

    with journal.phase("phase2", "フェーズ2: 壁面摩擦試験"):
        for condition_id in arguments.condition_ids:
            wall_condition = conditions[condition_id]
            condition_directory = output_root / wall_condition.directory_name
            inlet_csv_path = condition_directory / PRE_SHEAR_INLET_RELATIVE_PATH
            height_json_path = condition_directory / PRE_SHEAR_HEIGHT_RELATIVE_PATH
            if not inlet_csv_path.is_file():
                raise FileNotFoundError(
                    f"条件{condition_id}のプリせん断CSVがありません: {inlet_csv_path}"
                )
            if not height_json_path.is_file():
                raise FileNotFoundError(
                    f"条件{condition_id}のディスク高さJSONがありません: {height_json_path}"
                )
            disc_height_m = float(
                json.loads(height_json_path.read_text(encoding="utf-8"))["maximum_y_m"]
            )

            for load_kpa in arguments.loads:
                template = get_template_path(WALL_SECTION, f"shear_{load_kpa:g}kpa")
                if not template.is_file():
                    raise FileNotFoundError(
                        f"本せん断テンプレートが見つかりません: {template}"
                    )

                with journal.step(
                    f"{wall_condition.directory_name}_shear_{load_kpa:g}kpa",
                    f"壁面摩擦 条件{condition_id} {load_kpa:g}kPa",
                ):
                    journal.progress(
                        f"条件{condition_id} {load_kpa:g}kPa: "
                        f"壁面動摩擦={wall_condition.dynamic_friction} "
                        f"壁面静止摩擦={wall_condition.static_friction}"
                    )
                    print(f"      プリせん断CSV : {inlet_csv_path}")
                    print(
                        f"      ディスク高さ   : {disc_height_m} m"
                        f" -> {geometry_name} Translation Y"
                    )
                    print(f"      Time Plot     : {time_plot_name}")

                    client = PyRockyClient(
                        str(ROCKY_EXECUTABLE_PATH), headless=arguments.headless
                    )
                    result = run_wall_friction_shear_test(
                        client,
                        powder_condition,
                        wall_condition,
                        load_kpa,
                        template_project_path=template,
                        inlet_csv_path=inlet_csv_path,
                        disc_height_m=disc_height_m,
                        output_root=output_root,
                        disc_geometry_name=geometry_name,
                        wall_material_name=wall_material,
                        time_plot_name=time_plot_name,
                    )
                    csv_path = result["time_series_csv"]
                    print(
                        f"[OK] トルクCSV: {csv_path} "
                        f"(行数={result['row_count']} 時刻={result['time_range_s'][0]}"
                        f"〜{result['time_range_s'][1]}s)"
                    )

                    if arguments.skip_excel:
                        continue

                    times, forces, moments = read_shear_time_series(csv_path)
                    excel_result = update_shear_time_series(
                        workbook_path, condition_id, load_kpa, times, forces, moments
                    )
                    print(f"     貼付けシート   : {excel_result['sheet']}")
                    print(
                        f"     定常せん断応力 : {excel_result['steady_shear_stress_kpa']} kPa"
                    )
                    print(f"     定常傾き       : {excel_result['steady_slope']}")
                    journal.record_result(
                        f"wall_condition_{condition_id:02d}_{load_kpa:g}kpa",
                        {
                            "steady_shear_stress_kpa": excel_result[
                                "steady_shear_stress_kpa"
                            ],
                            "steady_slope": excel_result["steady_slope"],
                            "wall_dynamic_friction": wall_condition.dynamic_friction,
                            "wall_static_friction": wall_condition.static_friction,
                        },
                    )
                    if excel_result.get("formula_errors"):
                        print(f"     [警告] 数式エラー: {excel_result['formula_errors']}")

    print(f"進捗確認: poscap status --project-id {arguments.project_id} --verbose")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
