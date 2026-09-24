#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""既存のRockyプロジェクトのパラメータをCSVへ出力し、シミュレーションを実行する。"""

# ===============================================================
# Rockyのプロセス確認・終了コマンド
# ---------------------------------------------------------------
# Rockyのプロセス確認
#    Get-Process rocky -ErrorAction SilentlyContinue
# プロセス終了
#    Stop-Process -Name rocky -Force
# ===============================================================

from __future__ import annotations

import argparse
import csv
import os
import time
from pathlib import Path
from typing import Optional

import ansys.rocky.core as pyrocky

# ===============================================
# Rocky実行ファイルのパス
# ===============================================
ROCKY_EXECUTABLE_PATH = Path(r"C:\Program Files\ANSYS Inc\v252\Rocky\bin\Rocky.exe")

# ===============================================
# プロジェクトファイルの読み込み
# ===============================================
DEFAULT_PROJECT_PATH = Path(r"C:\Users\4104302\Downloads\Generate_Periodic0_2520384_25R1.rocky_archive_20260826\1ml_Filling_18.rocky")

# ===============================================
# 結果の出力先フォルダ
# ===============================================
DEFAULT_RESULTS_DIR = Path(r"C:\Users\4104302\OneDrive - Panasonic\pyrocky_test\results")

ROCKY_VERSION = 252

# study, Projectのオブジェクト取得
rocky = pyrocky.launch_rocky(
    rocky_exe=ROCKY_EXECUTABLE_PATH,
    rocky_version=ROCKY_VERSION,
    headless=False,
)
api = rocky.api
api.OpenProject(str(DEFAULT_PROJECT_PATH))

project = api.GetProject()
study = project.GetStudy()

# ===============================================
# 出力するPropertyの設定
# ===============================================
X_PROPERTY = "Particle X-Coordinate"
Y_PROPERTY = "Particle Y-Coordinate"

X_UNIT = "mm"
Y_UNIT = "mm"


def get_last_time_step(study):
    """
    保存されているシミュレーション結果から、
    最後のtime_stepと実際の時刻を取得する。
    """

    time_array = study.GetTimeSet()

    if time_array is None or len(time_array) == 0:
        raise RuntimeError(
            "シミュレーションの出力時刻を取得できませんでした。"
        )

    # 最後に保存されている結果のインデックス
    last_time_step = len(time_array) - 1
    last_time = float(time_array[last_time_step])

    return time_array, last_time_step, last_time


def get_property_array(
    process,
    property_name: str,
    time_step: int,
    unit: Optional[str] = None,
):
    """
    指定したtime_stepにおけるProperty配列を取得する。
    """

    grid_function = process.GetGridFunction(
        property_name
    )

    if grid_function is None:
        raise RuntimeError(
            f"Propertyを取得できませんでした: {property_name}"
        )

    if unit is None:
        values = grid_function.GetArray(
            time_step=time_step
        )
    else:
        values = grid_function.GetArray(
            unit=unit,
            time_step=time_step
        )

    return list(values)


def export_last_particle_properties(
    study,
    results_dir: Path,
):
    """
    最終出力時刻における粒子Propertyを取得し、
    Cross Plot相当のCSVとして保存する。
    """

    # -------------------------------------------
    # シミュレーション結果の確認
    # -------------------------------------------
    if not study.HasResults():
        raise RuntimeError(
            "プロジェクトにシミュレーション結果がありません。"
        )

    # -------------------------------------------
    # 最終出力時刻を取得
    # -------------------------------------------
    (
        time_array,
        last_time_step,
        last_time,
    ) = get_last_time_step(study)

    print(f"出力時刻数   : {len(time_array)}")
    print(f"最終time_step: {last_time_step}")
    print(f"最終出力時刻 : {last_time} s")

    # -------------------------------------------
    # Particlesオブジェクトを取得
    # -------------------------------------------
    particles = study.GetParticles()

    if particles is None:
        raise RuntimeError(
            "Particlesオブジェクトを取得できませんでした。"
        )

    # -------------------------------------------
    # 粒子IDを取得
    # -------------------------------------------
    particle_ids = get_property_array(
        process=particles,
        property_name="Particle ID",
        time_step=last_time_step,
        unit=None,
    )

    # -------------------------------------------
    # X軸にするPropertyを取得
    # -------------------------------------------
    x_values = get_property_array(
        process=particles,
        property_name=X_PROPERTY,
        time_step=last_time_step,
        unit=X_UNIT,
    )

    # -------------------------------------------
    # Y軸にするPropertyを取得
    # -------------------------------------------
    y_values = get_property_array(
        process=particles,
        property_name=Y_PROPERTY,
        time_step=last_time_step,
        unit=Y_UNIT,
    )

    # -------------------------------------------
    # 配列長の確認
    # -------------------------------------------
    lengths = {
        "Particle ID": len(particle_ids),
        X_PROPERTY: len(x_values),
        Y_PROPERTY: len(y_values),
    }

    print(f"取得データ数 : {lengths}")

    if len(set(lengths.values())) != 1:
        raise ValueError(
            "Particle ID、X軸Property、Y軸Propertyの"
            f"データ数が一致していません: {lengths}"
        )

    # -------------------------------------------
    # 出力フォルダを作成
    # -------------------------------------------
    results_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_csv_path = (
        results_dir
        / "particle_cross_plot_last_time.csv"
    )

    # -------------------------------------------
    # CSVに保存
    # -------------------------------------------
    with output_csv_path.open(
        mode="w",
        newline="",
        encoding="utf-8-sig",
    ) as csv_file:

        writer = csv.writer(csv_file)

        # ヘッダー
        writer.writerow(
            [
                "Particle ID",
                "Time [s]",
                f"{X_PROPERTY} [{X_UNIT}]",
                f"{Y_PROPERTY} [{Y_UNIT}]",
            ]
        )

        # データ
        for particle_id, x_value, y_value in zip(
            particle_ids,
            x_values,
            y_values,
        ):
            writer.writerow(
                [
                    particle_id,
                    last_time,
                    x_value,
                    y_value,
                ]
            )

    print("=" * 60)
    print("Cross Plot相当データを保存しました。")
    print(f"最終出力時刻 : {last_time} s")
    print(f"取得粒子数   : {len(particle_ids)}")
    print(f"CSV出力先    : {output_csv_path}")
    print("=" * 60)

    return output_csv_path


# ===============================================
# メイン処理
# ===============================================

try:
    if project is None:
        raise RuntimeError(
            "Projectオブジェクトを取得できませんでした。"
        )

    if study is None:
        raise RuntimeError(
            "Studyオブジェクトを取得できませんでした。"
        )

    print(
        "開いているプロジェクト:",
        project.GetProjectFilename(),
    )

    output_csv_path = export_last_particle_properties(
        study=study,
        results_dir=DEFAULT_RESULTS_DIR,
    )

except Exception as error:
    print("=" * 60)
    print("処理中にエラーが発生しました。")
    print(f"エラー種類: {type(error).__name__}")
    print(f"エラー内容: {error}")
    print("=" * 60)

    raise

#finally:
    # 処理終了時にRockyとの接続を閉じる
    # Rocky画面をそのまま残したい場合は、
    # 次の行をコメントアウトしてください。
    rocky.close()