"""シミュレーション実行と完了判定(docs/Rocky.md 13章)。プロセス終了のみでは完了とみなさない。"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from poscap_calibration.models import ShearCondition
from poscap_calibration.particle_distribution import load_particle_distribution
from poscap_calibration.rocky.client import RockyClient
from poscap_calibration.rocky.result_exporter import (
    PARTICLE_CUSTOM_INLET_COLUMNS,
    convert_particle_custom_inlet_csv,
)
from poscap_calibration.state.state_manager import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    write_status,
)

logger = logging.getLogger(__name__)

#: 読み戻した粉体パラメータが設定値と一致するとみなす相対許容誤差。
_PARAMETER_TOLERANCE = 1e-9


def run_particle_generation(
    client: RockyClient,
    distribution_csv_path: str | Path,
    template_project_path: str | Path,
    work_project_path: str | Path,
    user_process_name: str,
    output_csv_path: str | Path,
    *,
    time_step: int = 0,
    host: str = "127.0.0.1",
    port: int = 0,
) -> Path:
    """粒子発生シミュレーションを実行し、粒子データをCSV出力する(docs/workflow.md 10.1節)。

    Cross Plotが参照するUser Process(``user_process_name``)に含まれる粒子のみを
    対象時刻``time_step``(既定は0秒)で取得する。
    テンプレート原本は開かず``work_project_path``へ複製して使用するため、
    原本の結果や設定は変更されない。
    """
    distribution = load_particle_distribution(distribution_csv_path)
    work_path = copy_rocky_project(template_project_path, work_project_path)

    client.connect(host, port)
    try:
        client.open_project(work_path)
        client.delete_results()
        client.set_particle_property("size_distribution", distribution)
        client.save_project_as(work_path)
        client.run_simulation()

        if not client.is_completed():
            raise RuntimeError("粒子発生シミュレーションが正常終了しませんでした。")

        raw_csv_path = Path(
            client.export_user_process_particles(user_process_name, time_step)
        )
    finally:
        client.disconnect()

    output_path = Path(output_csv_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if raw_csv_path != output_path:
        shutil.copy2(raw_csv_path, output_path)

    logger.info(
        "particle generation: template=%s work=%s user_process=%s time_step=%s output=%s",
        template_project_path,
        work_project_path,
        user_process_name,
        time_step,
        output_path,
    )
    return output_path


def prepare_filling_input(
    client: RockyClient,
    raw_csv_path: str | Path,
    template_project_path: str | Path,
    work_project_path: str | Path,
    converted_csv_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
) -> Path:
    """充填インプットファイルを作成する(手順書1.2.6、docs/Rocky.md 7.3節)。

    粒子発生の生CSVをParticle Custom Inlet形式(x, y, z, size)へ変換して検証し、
    充填テンプレートの複製へ設定する。シミュレーションは実行しない。
    """
    converted_path = Path(converted_csv_path)
    converted = convert_particle_custom_inlet_csv(raw_csv_path, converted_path)
    if converted.empty:
        raise ValueError(f"Particle Custom Inlet CSVの粒子数が0です: {converted_path}")

    work_path = copy_rocky_project(template_project_path, work_project_path)

    client.connect(host, port)
    try:
        client.open_project(work_path)
        client.set_custom_inlet_csv(converted_path)
        client.save_project_as(work_path)
    finally:
        client.disconnect()

    logger.info(
        "filling input: template=%s work=%s inlet_csv=%s particles=%d",
        template_project_path,
        work_path,
        converted_path,
        len(converted),
    )
    return work_path


def copy_rocky_project(
    template_project_path: str | Path, work_project_path: str | Path
) -> Path:
    """テンプレートの``.rocky``と``.rocky.files``を作業フォルダへ複製する。

    テンプレート原本を開かずに複製することで、原本の変更・上書きを防ぐ。
    """
    template_path = Path(template_project_path)
    if not template_path.is_file():
        raise FileNotFoundError(f"Rockyテンプレートが見つかりません: {template_path}")

    work_path = Path(work_project_path)
    work_path.parent.mkdir(parents=True, exist_ok=True)
    if work_path.exists():
        work_path.unlink()
    shutil.copy2(template_path, work_path)
    _clear_readonly(work_path)

    template_files_dir = template_path.with_suffix(f"{template_path.suffix}.files")
    if template_files_dir.is_dir():
        work_files_dir = work_path.with_suffix(f"{work_path.suffix}.files")
        if work_files_dir.exists():
            shutil.rmtree(work_files_dir, onerror=_force_remove)
        # .lockはRocky起動中を示すファイル。particleは粒子テセレーションのキャッシュで、
        # OneDriveがクラウドプレースホルダー化するとRockyが保存時に削除できずWinError 5になる。
        # いずれも複製しない(particleはRockyが必要に応じて再生成する)。
        shutil.copytree(
            template_files_dir,
            work_files_dir,
            ignore=shutil.ignore_patterns("*.lock", "particle"),
        )
        _clear_readonly(work_files_dir)

    return work_path


def _clear_readonly(path: Path) -> None:
    """複製先の読み取り専用属性を解除する。

    OneDrive上のフォルダはReadOnly属性を持ち、``copytree``がそれを引き継ぐため、
    Rockyが保存時に粒子キャッシュを削除できずWinError 5になる。
    """
    targets = [path] if path.is_file() else [path, *path.rglob("*")]
    for target in targets:
        try:
            target.chmod(stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            continue


def _force_remove(function: Any, path: str, exc_info: Any) -> None:
    """読み取り専用属性を解除して削除を再試行する(``shutil.rmtree``のonerror)。"""
    try:
        os.chmod(path, stat.S_IWRITE)
        function(path)
    except OSError:
        raise


def run_filling(
    client: RockyClient,
    condition: ShearCondition,
    base_project_path: str | Path,
    output_root: str | Path,
    user_process_name: str,
    *,
    output_directory: str | Path | None = None,
    inlet_csv_path: str | Path | None = None,
    time_step: int = -1,
    project_filename: str = "Filling.rocky",
    raw_csv_filename: str = "particles_1ml_raw.csv",
    converted_csv_filename: str = "particles_1ml_inlet.csv",
    log_filename: str = "fill.log",
    host: str = "127.0.0.1",
    port: int = 0,
) -> Path:
    """1条件分の充填シミュレーションを実行する(手順書1.2.7、docs/Rocky.md 7章)。

    1.2.6で作成済みの充填プロジェクトを条件別フォルダへ複製して実行するため、
    条件1〜9をループ実行しても互いの結果を上書きしない。Solver設定は変更しない。
    結果は``user_process_name``の粒子のみを``time_step``(既定は最終時刻)で取得する。
    ``inlet_csv_path``を渡すと、実行前にParticle Custom Inletへ粒子位置CSVを設定する。
    """
    inlet_path = None
    if inlet_csv_path is not None:
        inlet_path = Path(inlet_csv_path).resolve()
        if not inlet_path.is_file():
            raise FileNotFoundError(
                f"Particle Custom Inlet用CSVが見つかりません: {inlet_path}"
            )

    condition_directory = (
        Path(output_directory)
        if output_directory is not None
        else Path(output_root) / condition.directory_name / "fill"
    )
    project_path = condition_directory / "project" / project_filename
    raw_csv_path = condition_directory / "raw" / raw_csv_filename
    converted_csv_path = condition_directory / "converted" / converted_csv_filename
    log_path = condition_directory / log_filename

    condition_directory.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    started_at = datetime.now(timezone.utc)
    status: dict[str, object] = {
        "condition_id": condition.condition_id,
        "step": "fill",
        "status": STATUS_FAILED,
        "started_at": started_at.isoformat(),
        "requested_parameters": {
            "rolling_resistance": condition.rolling_resistance,
            "dynamic_friction": condition.dynamic_friction,
            "static_friction": condition.static_friction,
        },
        "base_project": str(Path(base_project_path)),
        "inlet_csv": str(inlet_path) if inlet_path is not None else None,
        "user_process_name": user_process_name,
        "time_step": time_step,
    }

    try:
        logger.info(
            "fill start: condition=%d base=%s", condition.condition_id, base_project_path
        )
        copy_rocky_project(base_project_path, project_path)

        client.connect(host, port)
        try:
            client.open_project(project_path)
            client.delete_results()
            applied = client.set_powder_parameters(
                condition.rolling_resistance,
                condition.dynamic_friction,
                condition.static_friction,
            )
            verify_powder_parameters(condition, applied)
            status["applied_parameters"] = applied
            logger.info("fill parameters applied: %s", applied)

            if inlet_path is not None:
                client.set_custom_inlet_csv(inlet_path)
                logger.info("fill custom inlet set: %s", inlet_path)

            client.save_project_as(project_path)
            client.run_simulation()
            if not client.is_completed():
                raise RuntimeError(
                    f"条件{condition.condition_id}の充填シミュレーションが正常終了しませんでした。"
                )

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

        status.update(
            {
                "status": STATUS_COMPLETED,
                "particle_count": int(len(converted)),
                "outputs": {
                    "project": str(project_path),
                    "raw_csv": str(raw_csv_path),
                    "converted_csv": str(converted_csv_path),
                    "log": str(log_path),
                },
            }
        )
        logger.info(
            "fill completed: condition=%d particles=%d converted=%s",
            condition.condition_id,
            len(converted),
            converted_csv_path,
        )
        return converted_csv_path

    except Exception as error:
        status["error"] = f"{type(error).__name__}: {error}"
        logger.exception("fill failed: condition=%d", condition.condition_id)
        raise
    finally:
        status["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_status(condition_directory, status)
        file_handler.close()
        logger.removeHandler(file_handler)


def run_pre_shear(
    client: RockyClient,
    condition: ShearCondition,
    template_project_path: str | Path,
    inlet_csv_path: str | Path,
    output_root: str | Path,
    shear_cell_geometry_name: str,
    *,
    user_process_name: str | None = None,
    time_step: int = -1,
    project_filename: str = "Pre_shear.rocky",
    raw_csv_filename: str = "particles_raw.csv",
    converted_csv_filename: str = "particles_inlet.csv",
    height_json_filename: str = "shear_cell_height.json",
    log_filename: str = "pre_shear.log",
    host: str = "127.0.0.1",
    port: int = 0,
) -> Path:
    """1条件分のプリせん断シミュレーションを実行する(手順書1.2.7、docs/Rocky.md 8章)。

    充填結果のParticle Custom Inlet CSVを絶対パスで設定し、最終時刻のせん断セル高さと
    粒子データを保存する。テンプレート原本は開かず条件別フォルダへ複製して使用する。
    """
    inlet_path = Path(inlet_csv_path).resolve()
    if not inlet_path.is_file():
        raise FileNotFoundError(f"充填結果のCSVが見つかりません: {inlet_path}")

    condition_directory = Path(output_root) / condition.directory_name / "pre_shear"
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

    status: dict[str, object] = {
        "condition_id": condition.condition_id,
        "step": "pre_shear",
        "status": STATUS_FAILED,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "requested_parameters": {
            "rolling_resistance": condition.rolling_resistance,
            "dynamic_friction": condition.dynamic_friction,
            "static_friction": condition.static_friction,
        },
        "template_project": str(Path(template_project_path)),
        "inlet_csv": str(inlet_path),
        "shear_cell_geometry": shear_cell_geometry_name,
        "user_process_name": user_process_name,
        "time_step": time_step,
    }

    try:
        logger.info(
            "pre_shear start: condition=%d template=%s inlet=%s",
            condition.condition_id,
            template_project_path,
            inlet_path,
        )
        copy_rocky_project(template_project_path, project_path)

        client.connect(host, port)
        try:
            client.open_project(project_path)
            client.delete_results()

            applied = client.set_powder_parameters(
                condition.rolling_resistance,
                condition.dynamic_friction,
                condition.static_friction,
            )
            verify_powder_parameters(condition, applied)
            status["applied_parameters"] = applied
            logger.info("pre_shear parameters applied: %s", applied)

            client.set_custom_inlet_csv(inlet_path)
            client.save_project_as(project_path)

            client.run_simulation()
            if not client.is_completed():
                raise RuntimeError(
                    f"条件{condition.condition_id}のプリせん断シミュレーションが正常終了しませんでした。"
                )

            shear_cell_height = client.get_geometry_max_y(
                shear_cell_geometry_name, time_step
            )
            exported_csv_path = Path(
                client.export_user_process_particles(user_process_name, time_step)
            )
        finally:
            client.disconnect()

        height_json_path.parent.mkdir(parents=True, exist_ok=True)
        height_json_path.write_text(
            json.dumps(shear_cell_height, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info(
            "pre_shear shear cell height: geometry=%s time=%ss maximum_y=%s%s",
            shear_cell_height["geometry"],
            shear_cell_height["time_s"],
            shear_cell_height["maximum_y_m"],
            shear_cell_height["unit"],
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
                "shear_cell_height": shear_cell_height,
                "outputs": {
                    "project": str(project_path),
                    "raw_csv": str(raw_csv_path),
                    "shear_cell_height_json": str(height_json_path),
                    "converted_csv": str(converted_csv_path),
                    "log": str(log_path),
                },
            }
        )
        logger.info(
            "pre_shear completed: condition=%d particles=%d converted=%s",
            condition.condition_id,
            len(converted),
            converted_csv_path,
        )
        return converted_csv_path

    except Exception as error:
        status["error"] = f"{type(error).__name__}: {error}"
        logger.exception("pre_shear failed: condition=%d", condition.condition_id)
        raise
    finally:
        status["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_status(condition_directory, status)
        file_handler.close()
        logger.removeHandler(file_handler)


def run_shear_test(
    client: RockyClient,
    condition: ShearCondition,
    load_kpa: float,
    template_project_path: str | Path,
    inlet_csv_path: str | Path,
    shear_cell_height_m: float,
    output_root: str | Path,
    shear_cell_geometry_name: str,
    *,
    time_entity_name: str = "Lid Translational Motion",
    force_entity_name: str = "Lid Translational Motion",
    force_curve_name: str = "Force Y",
    moment_entity_name: str = "Lid Rotational Motion",
    moment_curve_name: str = "Moment Y",
    host: str = "127.0.0.1",
    port: int = 0,
) -> Path:
    """1条件・1荷重分の本せん断シミュレーションを実行する(手順書1.2.7、docs/Rocky.md 9章)。

    荷重とテンプレートを引数で受け取る共通処理のため、3/5/7 kPaで同じ経路を使う。
    テンプレート原本は開かず荷重別フォルダへ複製し、結果は独立して保存する。
    """
    inlet_path = _validate_inlet_csv(Path(inlet_csv_path), condition, load_kpa)

    step_name = f"shear_{_format_load(load_kpa)}kpa"
    condition_directory = Path(output_root) / condition.directory_name / step_name
    project_path = condition_directory / "project" / Path(template_project_path).name
    time_series_csv_path = (
        condition_directory / "raw" / f"{_format_load(load_kpa)}kPa_ShearTest_time.csv"
    )
    log_path = condition_directory / f"{step_name}.log"

    condition_directory.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    status: dict[str, object] = {
        "condition_id": condition.condition_id,
        "step": step_name,
        "load_kpa": load_kpa,
        "status": STATUS_FAILED,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "requested_parameters": {
            "rolling_resistance": condition.rolling_resistance,
            "dynamic_friction": condition.dynamic_friction,
            "static_friction": condition.static_friction,
        },
        "template_project": str(Path(template_project_path)),
        "inlet_csv": str(inlet_path),
        "shear_cell_geometry": shear_cell_geometry_name,
        "requested_shear_cell_height_m": float(shear_cell_height_m),
    }

    try:
        logger.info(
            "shear start: condition=%d load=%skPa template=%s inlet=%s height=%sm",
            condition.condition_id,
            load_kpa,
            template_project_path,
            inlet_path,
            shear_cell_height_m,
        )
        copy_rocky_project(template_project_path, project_path)

        client.connect(host, port)
        try:
            client.open_project(project_path)
            client.delete_results()

            applied = client.set_powder_parameters(
                condition.rolling_resistance,
                condition.dynamic_friction,
                condition.static_friction,
            )
            verify_powder_parameters(condition, applied)
            status["applied_parameters"] = applied

            client.set_custom_inlet_csv(inlet_path)

            client.set_geometry_translation_y(
                shear_cell_geometry_name, float(shear_cell_height_m)
            )
            applied_height = float(
                client.get_geometry_translation_y(shear_cell_geometry_name)
            )
            if not math.isclose(
                applied_height,
                float(shear_cell_height_m),
                rel_tol=_PARAMETER_TOLERANCE,
                abs_tol=_PARAMETER_TOLERANCE,
            ):
                raise RuntimeError(
                    f"条件{condition.condition_id} 荷重{load_kpa}kPa: "
                    f"Geometry '{shear_cell_geometry_name}' のY移動量が設定値と一致しません"
                    f"(設定={shear_cell_height_m} 読み戻し={applied_height})。"
                )
            status["applied_shear_cell_height_m"] = applied_height
            logger.info(
                "shear settings applied: parameters=%s shear_cell_height=%sm",
                applied,
                applied_height,
            )

            client.save_project_as(project_path)
            client.run_simulation()
            if not client.is_completed():
                raise RuntimeError(
                    f"条件{condition.condition_id} 荷重{load_kpa}kPaの"
                    "本せん断シミュレーションが正常終了しませんでした。"
                )

            times, force_values = client.get_curve(force_entity_name, force_curve_name)
            moment_times, moment_values = client.get_curve(
                moment_entity_name, moment_curve_name
            )
        finally:
            client.disconnect()

        _validate_time_series(
            condition,
            load_kpa,
            times,
            force_values,
            moment_times,
            moment_values,
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
                "curves": {
                    "time_entity": time_entity_name,
                    "force": {"entity": force_entity_name, "curve": force_curve_name},
                    "moment": {"entity": moment_entity_name, "curve": moment_curve_name},
                },
                "outputs": {
                    "project": str(project_path),
                    "time_series_csv": str(time_series_csv_path),
                    "log": str(log_path),
                },
            }
        )
        logger.info(
            "shear completed: condition=%d load=%skPa rows=%d csv=%s",
            condition.condition_id,
            load_kpa,
            len(times),
            time_series_csv_path,
        )
        return time_series_csv_path

    except Exception as error:
        status["error"] = f"{type(error).__name__}: {error}"
        logger.exception(
            "shear failed: condition=%d load=%skPa", condition.condition_id, load_kpa
        )
        raise
    finally:
        status["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_status(condition_directory, status)
        file_handler.close()
        logger.removeHandler(file_handler)


def _format_load(load_kpa: float) -> str:
    """``3``や``3.0``を``3``、``3.5``を``3.5``としてフォルダ名・ファイル名に使う。"""
    return f"{load_kpa:g}"


def shear_time_series_csv_path(
    output_root: str | Path, condition: ShearCondition, load_kpa: float
) -> Path:
    """``run_shear_test``が出力する時系列CSVのパスを返す。"""
    load_text = _format_load(load_kpa)
    return (
        Path(output_root)
        / condition.directory_name
        / f"shear_{load_text}kpa"
        / "raw"
        / f"{load_text}kPa_ShearTest_time.csv"
    )


def read_shear_time_series(
    csv_path: str | Path,
) -> tuple[list[float], list[float], list[float]]:
    """本せん断の時系列CSVを (Time, Force Y, Moment Y) として読み込む。"""
    times: list[float] = []
    forces: list[float] = []
    moments: list[float] = []
    with Path(csv_path).open(encoding="utf-8") as csv_file:
        next(csv_file)
        for line in csv_file:
            if not line.strip():
                continue
            time_text, force_text, moment_text = line.rstrip("\n").split(",")
            times.append(float(time_text))
            forces.append(float(force_text))
            moments.append(float(moment_text))
    return times, forces, moments


def _validate_inlet_csv(
    inlet_csv_path: Path, condition: ShearCondition, load_kpa: float
) -> Path:
    """Particle Custom Inlet CSVの存在・空データ・必須列を検証し絶対パスを返す。"""
    context = f"条件{condition.condition_id} 荷重{load_kpa}kPa"
    inlet_path = inlet_csv_path.resolve()
    if not inlet_path.is_file():
        raise FileNotFoundError(f"{context}: 入力CSVが見つかりません: {inlet_path}")

    frame = pd.read_csv(inlet_path)
    missing = set(PARTICLE_CUSTOM_INLET_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(
            f"{context}: 入力CSVに必須列がありません: {sorted(missing)} ({inlet_path})"
        )
    if frame.empty:
        raise ValueError(f"{context}: 入力CSVにデータがありません: {inlet_path}")

    return inlet_path


def _validate_time_series(
    condition: ShearCondition,
    load_kpa: float,
    times: list[float],
    force_values: list[float],
    moment_times: list[float],
    moment_values: list[float],
) -> None:
    """時系列データの行対応・配列長・空データ・NaNを検証する。"""
    context = f"条件{condition.condition_id} 荷重{load_kpa}kPa"
    if not times:
        raise ValueError(f"{context}: 時系列データが空です。")

    lengths = {
        "time": len(times),
        "force_y": len(force_values),
        "moment_time": len(moment_times),
        "moment_y": len(moment_values),
    }
    if len(set(lengths.values())) != 1:
        raise ValueError(f"{context}: 時系列データの配列長が一致しません: {lengths}")

    mismatched = [
        index
        for index, (time_value, moment_time) in enumerate(zip(times, moment_times))
        if not math.isclose(time_value, moment_time, rel_tol=1e-9, abs_tol=1e-12)
    ]
    if mismatched:
        raise ValueError(
            f"{context}: Force YとMoment Yの時刻が一致しません(先頭の不一致行: {mismatched[:5]})。"
        )

    for label, values in (
        ("Time", times),
        ("Force Y", force_values),
        ("Moment Y", moment_values),
    ):
        invalid = [index for index, value in enumerate(values) if not math.isfinite(value)]
        if invalid:
            raise ValueError(
                f"{context}: {label}にNaNまたは無限大が含まれています"
                f"(先頭の該当行: {invalid[:5]})。"
            )


def verify_powder_parameters(
    condition: ShearCondition, applied: dict[str, float]
) -> None:
    """Rockyから読み戻した粉体パラメータが設定値と一致することを確認する。"""
    expected = {
        "rolling_resistance": condition.rolling_resistance,
        "dynamic_friction": condition.dynamic_friction,
        "static_friction": condition.static_friction,
    }
    mismatches = {
        key: {"expected": value, "actual": applied.get(key)}
        for key, value in expected.items()
        if applied.get(key) is None
        or not math.isclose(applied[key], value, rel_tol=_PARAMETER_TOLERANCE, abs_tol=_PARAMETER_TOLERANCE)
    }
    if mismatches:
        raise RuntimeError(
            f"条件{condition.condition_id}の粉体パラメータが設定値と一致しません: {mismatches}"
        )
