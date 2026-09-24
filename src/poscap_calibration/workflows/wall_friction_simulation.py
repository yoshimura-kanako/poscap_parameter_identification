"""フェーズ2の充填・プリせん断シミュレーション(手順書Phase2 1.2.5以降)。

充填はせん断試験と共通のテンプレート・処理を流用し、プリせん断のみ壁面摩擦条件
(壁面動摩擦係数・壁面静止摩擦係数)を追加設定する。
"""

from __future__ import annotations

import json
import logging
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from poscap_calibration.models import ShearCondition, WallFrictionCondition
from poscap_calibration.rocky.client import RockyClient
from poscap_calibration.rocky.result_exporter import convert_particle_custom_inlet_csv
from poscap_calibration.rocky.simulation_runner import (
    copy_rocky_project,
    run_filling,
    verify_powder_parameters,
)
from poscap_calibration.state.state_manager import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    write_status,
)

logger = logging.getLogger(__name__)

FILL_DIRECTORY_NAME = "fill"
FILL_INLET_RELATIVE_PATH = Path(FILL_DIRECTORY_NAME) / "converted" / "particles_1ml_inlet.csv"
PRE_SHEAR_INLET_RELATIVE_PATH = Path("pre_shear") / "converted" / "particles_inlet.csv"
PRE_SHEAR_HEIGHT_RELATIVE_PATH = Path("pre_shear") / "raw" / "disc_height.json"


def run_wall_friction_filling(
    client: RockyClient,
    powder_condition: ShearCondition,
    base_project_path: str | Path,
    output_root: str | Path,
    user_process_name: str,
    *,
    inlet_csv_path: str | Path | None = None,
    time_step: int = -1,
    host: str = "127.0.0.1",
    port: int = 0,
) -> Path:
    """フェーズ2の充填シミュレーションを実行する(手順書Phase2 1.2.5)。

    せん断試験と同一処理のため``run_filling``を流用し、出力先のみPhase2側へ向ける。
    充填結果は壁面摩擦3条件で共有する。
    """
    fill_directory = Path(output_root) / FILL_DIRECTORY_NAME
    converted_csv_path = run_filling(
        client,
        powder_condition,
        base_project_path,
        output_root,
        user_process_name,
        output_directory=fill_directory,
        inlet_csv_path=inlet_csv_path,
        time_step=time_step,
        host=host,
        port=port,
    )
    logger.info("wall friction filling completed: converted=%s", converted_csv_path)
    return converted_csv_path


def wall_friction_fill_inlet_csv_path(output_root: str | Path) -> Path:
    """``run_wall_friction_filling``が出力するParticle Custom Inlet CSVのパスを返す。"""
    return (
        Path(output_root) / FILL_INLET_RELATIVE_PATH
    )


def export_wall_friction_fill_particles(
    client: RockyClient,
    project_path: str | Path,
    output_root: str | Path,
    powder_condition: ShearCondition,
    user_process_name: str,
    *,
    time_step: int = -1,
    raw_csv_filename: str = "particles_1ml_raw.csv",
    host: str = "127.0.0.1",
    port: int = 0,
) -> Path:
    """計算済み充填プロジェクトから粒子を取得し、Particle Custom Inlet CSVを作成する。

    ``StartSimulation``が返らずシミュレーションだけ完了した場合など、
    後処理のみをやり直すために使う(シミュレーションは実行しない)。
    """
    project = Path(project_path)
    if not project.is_file():
        raise FileNotFoundError(f"充填プロジェクトが見つかりません: {project}")

    fill_directory = Path(output_root) / FILL_DIRECTORY_NAME
    raw_csv_path = fill_directory / "raw" / raw_csv_filename
    converted_csv_path = (
        Path(output_root) / FILL_INLET_RELATIVE_PATH
    )

    client.connect(host, port)
    try:
        client.open_project(project)
        exported_csv_path = Path(
            client.export_user_process_particles(user_process_name, time_step)
        )
    finally:
        client.disconnect()

    raw_csv_path.parent.mkdir(parents=True, exist_ok=True)
    if exported_csv_path != raw_csv_path:
        shutil.copy2(exported_csv_path, raw_csv_path)

    converted = convert_particle_custom_inlet_csv(raw_csv_path, converted_csv_path)
    if converted.empty:
        raise ValueError(f"充填結果の粒子数が0です: {converted_csv_path}")

    logger.info(
        "wall friction fill export: project=%s particles=%d converted=%s",
        project,
        len(converted),
        converted_csv_path,
    )
    return converted_csv_path


def run_wall_friction_pre_shear(
    client: RockyClient,
    powder_condition: ShearCondition,
    wall_condition: WallFrictionCondition,
    template_project_path: str | Path,
    inlet_csv_path: str | Path,
    output_root: str | Path,
    disc_geometry_name: str,
    *,
    wall_material_name: str | None = None,
    user_process_name: str | None = None,
    time_step: int = -1,
    project_filename: str = "Pre_shear_9kPa.rocky",
    raw_csv_filename: str = "particles_raw.csv",
    converted_csv_filename: str = "particles_inlet.csv",
    height_json_filename: str = "disc_height.json",
    log_filename: str = "pre_shear.log",
    host: str = "127.0.0.1",
    port: int = 0,
) -> dict[str, Any]:
    """壁面摩擦1条件分のプリせん断を実行する(手順書Phase2 1.2.6)。

    粉体パラメータに加えて壁面摩擦条件を設定し、最終時刻のディスク高さと粒子CSVを保存する。
    条件2・3も同じ経路で実行できるよう、条件は引数で受け取る。
    """
    inlet_path = Path(inlet_csv_path).resolve()
    if not inlet_path.is_file():
        raise FileNotFoundError(f"充填結果のCSVが見つかりません: {inlet_path}")

    condition_directory = Path(output_root) / wall_condition.directory_name / "pre_shear"
    project_path = condition_directory / "project" / project_filename
    raw_csv_path = condition_directory / "raw" / raw_csv_filename
    height_json_path = condition_directory / "raw" / height_json_filename
    converted_csv_path = condition_directory / "converted" / converted_csv_filename
    log_path = condition_directory / log_filename

    condition_directory.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    status: dict[str, Any] = {
        "condition_id": wall_condition.condition_id,
        "step": "wall_pre_shear",
        "status": STATUS_FAILED,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "requested_powder_parameters": {
            "rolling_resistance": powder_condition.rolling_resistance,
            "dynamic_friction": powder_condition.dynamic_friction,
            "static_friction": powder_condition.static_friction,
        },
        "requested_wall_parameters": {
            "dynamic_friction": wall_condition.dynamic_friction,
            "static_friction": wall_condition.static_friction,
        },
        "template_project": str(Path(template_project_path)),
        "inlet_csv": str(inlet_path),
        "disc_geometry": disc_geometry_name,
        "user_process_name": user_process_name,
        "time_step": time_step,
    }

    try:
        logger.info(
            "wall pre_shear start: condition=%d template=%s inlet=%s",
            wall_condition.condition_id,
            template_project_path,
            inlet_path,
        )
        copy_rocky_project(template_project_path, project_path)

        client.connect(host, port)
        try:
            client.open_project(project_path)
            client.delete_results()

            applied_powder = client.set_powder_parameters(
                powder_condition.rolling_resistance,
                powder_condition.dynamic_friction,
                powder_condition.static_friction,
            )
            verify_powder_parameters(powder_condition, applied_powder)
            status["applied_powder_parameters"] = applied_powder

            applied_wall = client.set_wall_friction_parameters(
                wall_condition.dynamic_friction,
                wall_condition.static_friction,
                geometry_name=disc_geometry_name,
                wall_material_name=wall_material_name,
            )
            _verify_wall_parameters(wall_condition, applied_wall)
            status["applied_wall_parameters"] = applied_wall
            logger.info(
                "wall pre_shear parameters applied: powder=%s wall=%s",
                applied_powder,
                applied_wall,
            )

            client.set_custom_inlet_csv(inlet_path)
            client.save_project_as(project_path)

            client.run_simulation()
            if not client.is_completed():
                raise RuntimeError(
                    f"壁面摩擦条件{wall_condition.condition_id}の"
                    "プリせん断シミュレーションが正常終了しませんでした。"
                )

            disc_height = client.get_geometry_max_y(disc_geometry_name, time_step)
            exported_csv_path = Path(
                client.export_user_process_particles(user_process_name, time_step)
            )
        finally:
            client.disconnect()

        height_json_path.parent.mkdir(parents=True, exist_ok=True)
        height_json_path.write_text(
            json.dumps(disc_height, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info(
            "wall pre_shear disc height: geometry=%s time=%ss maximum_y=%s%s",
            disc_height["geometry"],
            disc_height["time_s"],
            disc_height["maximum_y_m"],
            disc_height["unit"],
        )

        raw_csv_path.parent.mkdir(parents=True, exist_ok=True)
        if exported_csv_path != raw_csv_path:
            shutil.copy2(exported_csv_path, raw_csv_path)

        converted = convert_particle_custom_inlet_csv(raw_csv_path, converted_csv_path)
        if converted.empty:
            raise ValueError(f"プリせん断結果の粒子数が0です: {converted_csv_path}")

        status.update(
            {
                "status": STATUS_COMPLETED,
                "particle_count": int(len(converted)),
                "disc_height": disc_height,
                "outputs": {
                    "project": str(project_path),
                    "raw_csv": str(raw_csv_path),
                    "disc_height_json": str(height_json_path),
                    "converted_csv": str(converted_csv_path),
                    "log": str(log_path),
                },
            }
        )
        logger.info(
            "wall pre_shear completed: condition=%d particles=%d converted=%s",
            wall_condition.condition_id,
            len(converted),
            converted_csv_path,
        )
        return {
            "converted_csv": converted_csv_path,
            "disc_height": disc_height,
            "particle_count": int(len(converted)),
            "disc_height_json": height_json_path,
        }

    except Exception as error:
        status["error"] = f"{type(error).__name__}: {error}"
        logger.exception(
            "wall pre_shear failed: condition=%d", wall_condition.condition_id
        )
        raise
    finally:
        status["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_status(condition_directory, status)
        file_handler.close()
        logger.removeHandler(file_handler)


def wall_shear_step_name(load_kpa: float) -> str:
    """``shear_3kpa``形式のステップ名を返す(3/5/7 kPa共通)。"""
    return f"shear_{load_kpa:g}kpa"


def wall_shear_time_series_csv_path(
    output_root: str | Path, wall_condition: WallFrictionCondition, load_kpa: float
) -> Path:
    """``run_wall_friction_shear_test``が出力するトルク時系列CSVのパスを返す。"""
    return (
        Path(output_root)
        / wall_condition.directory_name
        / wall_shear_step_name(load_kpa)
        / "raw"
        / f"{load_kpa:g}kPa_WallShearTest_time.csv"
    )


def run_wall_friction_shear_test(
    client: RockyClient,
    powder_condition: ShearCondition,
    wall_condition: WallFrictionCondition,
    load_kpa: float,
    template_project_path: str | Path,
    inlet_csv_path: str | Path,
    disc_height_m: float,
    output_root: str | Path,
    disc_geometry_name: str,
    *,
    wall_material_name: str | None = None,
    time_plot_name: str = "Lid_Moment_Force",
    force_entity_name: str = "Lid Translational Motion",
    force_curve_name: str = "Force Y",
    moment_entity_name: str = "Lid Rotational Motion",
    moment_curve_name: str = "Moment Y",
    host: str = "127.0.0.1",
    port: int = 0,
) -> dict[str, Any]:
    """壁面摩擦1条件・1荷重分の本せん断を実行する(手順書Phase2 1.2.7)。

    荷重とテンプレートを引数で受け取る共通処理のため、3/5/7 kPaで同じ経路を使う。
    ディスク高さはGeometryのTransform > Translation > Yへ設定する。
    """
    inlet_path = Path(inlet_csv_path).resolve()
    if not inlet_path.is_file():
        raise FileNotFoundError(f"プリせん断結果のCSVが見つかりません: {inlet_path}")
    if not math.isfinite(disc_height_m):
        raise ValueError(f"disc_height_mは有限値で指定してください: {disc_height_m}")

    step_name = wall_shear_step_name(load_kpa)
    condition_directory = Path(output_root) / wall_condition.directory_name / step_name
    project_path = condition_directory / "project" / Path(template_project_path).name
    time_series_csv_path = wall_shear_time_series_csv_path(
        output_root, wall_condition, load_kpa
    )
    log_path = condition_directory / f"{step_name}.log"

    condition_directory.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    status: dict[str, Any] = {
        "condition_id": wall_condition.condition_id,
        "step": step_name,
        "load_kpa": float(load_kpa),
        "status": STATUS_FAILED,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "requested_powder_parameters": {
            "rolling_resistance": powder_condition.rolling_resistance,
            "dynamic_friction": powder_condition.dynamic_friction,
            "static_friction": powder_condition.static_friction,
        },
        "requested_wall_parameters": {
            "dynamic_friction": wall_condition.dynamic_friction,
            "static_friction": wall_condition.static_friction,
        },
        "template_project": str(Path(template_project_path)),
        "inlet_csv": str(inlet_path),
        "disc_geometry": disc_geometry_name,
        "requested_disc_height_m": float(disc_height_m),
        "time_plot": time_plot_name,
    }

    try:
        logger.info(
            "wall shear start: condition=%d load=%skPa template=%s inlet=%s height=%sm",
            wall_condition.condition_id,
            load_kpa,
            template_project_path,
            inlet_path,
            disc_height_m,
        )
        copy_rocky_project(template_project_path, project_path)

        client.connect(host, port)
        try:
            client.open_project(project_path)
            client.delete_results()

            applied_powder = client.set_powder_parameters(
                powder_condition.rolling_resistance,
                powder_condition.dynamic_friction,
                powder_condition.static_friction,
            )
            verify_powder_parameters(powder_condition, applied_powder)
            status["applied_powder_parameters"] = applied_powder

            applied_wall = client.set_wall_friction_parameters(
                wall_condition.dynamic_friction,
                wall_condition.static_friction,
                geometry_name=disc_geometry_name,
                wall_material_name=wall_material_name,
            )
            _verify_wall_parameters(wall_condition, applied_wall)
            status["applied_wall_parameters"] = applied_wall

            client.set_custom_inlet_csv(inlet_path)

            client.set_geometry_translation_y(disc_geometry_name, float(disc_height_m))
            applied_height = float(
                client.get_geometry_translation_y(disc_geometry_name)
            )
            if not math.isclose(
                applied_height, float(disc_height_m), rel_tol=1e-9, abs_tol=1e-12
            ):
                raise RuntimeError(
                    f"条件{wall_condition.condition_id} 荷重{load_kpa}kPa: "
                    f"Geometry '{disc_geometry_name}' のY移動量が設定値と一致しません"
                    f"(設定={disc_height_m} 読み戻し={applied_height})。"
                )
            status["applied_disc_height_m"] = applied_height
            logger.info(
                "wall shear settings applied: powder=%s wall=%s disc_height=%sm",
                applied_powder,
                applied_wall,
                applied_height,
            )

            client.save_project_as(project_path)
            client.run_simulation()
            if not client.is_completed():
                raise RuntimeError(
                    f"条件{wall_condition.condition_id} 荷重{load_kpa}kPaの"
                    "本せん断シミュレーションが正常終了しませんでした。"
                )

            times, force_values = client.get_curve(force_entity_name, force_curve_name)
            moment_times, moment_values = client.get_curve(
                moment_entity_name, moment_curve_name
            )
        finally:
            client.disconnect()

        if not times:
            raise ValueError(
                f"条件{wall_condition.condition_id} 荷重{load_kpa}kPaの時系列が空です。"
            )
        if not (len(times) == len(force_values) == len(moment_values) == len(moment_times)):
            raise ValueError(
                "時系列の長さが一致しません: "
                f"time={len(times)} force={len(force_values)} moment={len(moment_values)}"
            )

        time_series_csv_path.parent.mkdir(parents=True, exist_ok=True)
        with time_series_csv_path.open("w", encoding="utf-8", newline="") as csv_file:
            csv_file.write(
                f"Date [s],{force_curve_name} ({force_entity_name}) [N],"
                f"{moment_curve_name} ({moment_entity_name}) [N.m]\n"
            )
            for time_value, force_value, moment_value in zip(
                times, force_values, moment_values
            ):
                csv_file.write(f"{time_value},{force_value},{moment_value}\n")

        status.update(
            {
                "status": STATUS_COMPLETED,
                "row_count": len(times),
                "time_range_s": [times[0], times[-1]],
                "outputs": {
                    "project": str(project_path),
                    "time_series_csv": str(time_series_csv_path),
                    "log": str(log_path),
                },
            }
        )
        logger.info(
            "wall shear completed: condition=%d load=%skPa rows=%d csv=%s",
            wall_condition.condition_id,
            load_kpa,
            len(times),
            time_series_csv_path,
        )
        return {
            "time_series_csv": time_series_csv_path,
            "row_count": len(times),
            "time_range_s": (times[0], times[-1]),
            "applied_disc_height_m": status["applied_disc_height_m"],
        }

    except Exception as error:
        status["error"] = f"{type(error).__name__}: {error}"
        logger.exception(
            "wall shear failed: condition=%d load=%skPa",
            wall_condition.condition_id,
            load_kpa,
        )
        raise
    finally:
        status["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_status(condition_directory, status)
        file_handler.close()
        logger.removeHandler(file_handler)


def _verify_wall_parameters(
    condition: WallFrictionCondition, applied: dict[str, Any]
) -> None:
    """Rockyから読み戻した壁面摩擦係数が設定値と一致することを確認する。"""
    expected = {
        "dynamic_friction": condition.dynamic_friction,
        "static_friction": condition.static_friction,
    }
    mismatches = {
        key: {"expected": value, "actual": applied.get(key)}
        for key, value in expected.items()
        if applied.get(key) is None
        or not math.isclose(float(applied[key]), value, rel_tol=1e-9, abs_tol=1e-9)
    }
    if mismatches:
        raise RuntimeError(
            f"壁面摩擦条件{condition.condition_id}の摩擦係数が設定値と一致しません: {mismatches}"
        )
