"""粒度分布データの読込みとRocky入力形式への変換(FR-03)。"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd


class ParticleDistributionError(ValueError):
    """粒度分布データが不正な場合に送出する例外。"""


def load_particle_distribution(csv_path: str | Path) -> list[tuple[float, float]]:
    """粒度分布CSV(``particle_size[µm]``, ``cumulative_mass_percent``)を読み込む。

    粒子径はCSV記載のµm単位のまま返す(Rockyへ設定する際にm換算する)。
    Rocky入力順(粒子径の降順)に並べ替えた ``(粒子径[µm], 累積質量%)`` のリストを返す。
    """
    path = Path(csv_path)
    df = pd.read_csv(path)

    size_column = "particle_size[µm]" if "particle_size[µm]" in df.columns else "particle_size"
    required_columns = {size_column, "cumulative_mass_percent"}
    missing = required_columns - set(df.columns)
    if missing:
        raise ParticleDistributionError(f"必須列がありません: {sorted(missing)}")

    if df.empty:
        raise ParticleDistributionError("粒度分布データが空です。")
    if (df[size_column] <= 0).any():
        raise ParticleDistributionError("particle_sizeは正の値である必要があります。")

    df = df.sort_values(size_column, ascending=False).reset_index(drop=True)
    percent = df["cumulative_mass_percent"]

    if not percent.is_monotonic_decreasing:
        raise ParticleDistributionError(
            "cumulative_mass_percentは粒子径の降順で単調減少である必要があります。"
        )
    if not math.isclose(percent.iloc[0], 100.0, abs_tol=1e-6):
        raise ParticleDistributionError("cumulative_mass_percentの最大粒径での値は100である必要があります。")

    return list(zip(df[size_column].tolist(), percent.tolist()))
