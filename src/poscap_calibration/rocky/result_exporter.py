"""Cross Plot/Time Plot結果のCSV取得およびParticle Custom Inlet形式への変換(FR-08)。"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

#: 出力列名(この順序で固定)。
PARTICLE_CUSTOM_INLET_COLUMNS: tuple[str, ...] = ("x", "y", "z", "size")

# 生データの列名はプロジェクト名・粒子IDなどを含むため、列番号ではなくキーワードで特定する。
_COLUMN_PATTERNS: dict[str, re.Pattern[str]] = {
    "x": re.compile(r"coordinate\s*:?\s*x\b", re.IGNORECASE),
    "y": re.compile(r"coordinate\s*:?\s*y\b", re.IGNORECASE),
    "z": re.compile(r"coordinate\s*:?\s*z\b", re.IGNORECASE),
    "size": re.compile(r"particle\s*size\b", re.IGNORECASE),
}


class ParticleCustomInletConversionError(ValueError):
    """Particle Custom Inlet CSVへの変換に失敗した場合に送出する例外。"""


def _find_column(columns: pd.Index, key: str, pattern: re.Pattern[str]) -> str:
    matches = [column for column in columns if pattern.search(str(column))]
    if not matches:
        raise ParticleCustomInletConversionError(
            f"'{key}'に対応する列が見つかりません(検索対象列: {list(columns)})。"
        )
    if len(matches) > 1:
        raise ParticleCustomInletConversionError(
            f"'{key}'に対応する列が複数見つかりました: {matches}"
        )
    return matches[0]


def convert_particle_custom_inlet(raw: pd.DataFrame) -> pd.DataFrame:
    """Rocky出力DataFrameをParticle Custom Inlet形式(x, y, z, size)へ変換する。

    列は番号ではなく列名のキーワード(``Coordinate : X`` 等、``Particle Size``)から特定する。
    """
    column_map = {
        key: _find_column(raw.columns, key, pattern)
        for key, pattern in _COLUMN_PATTERNS.items()
    }
    converted = pd.DataFrame(
        {key: raw[column_map[key]] for key in PARTICLE_CUSTOM_INLET_COLUMNS}
    )

    if converted.isna().any().any():
        raise ParticleCustomInletConversionError("変換後のデータに欠損値が含まれています。")
    if not converted.map(lambda v: isinstance(v, (int, float))).all().all():
        raise ParticleCustomInletConversionError("変換後のデータに数値以外の値が含まれています。")
    if (converted["size"] <= 0).any():
        raise ParticleCustomInletConversionError("size列に0以下の値が含まれています。")

    return converted.reset_index(drop=True)


def convert_particle_custom_inlet_csv(
    input_path: str | Path, output_path: str | Path
) -> pd.DataFrame:
    """Rocky出力CSV(生データ)を読み込み、Particle Custom Inlet CSVとして保存する。"""
    raw = pd.read_csv(Path(input_path))
    converted = convert_particle_custom_inlet(raw)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    converted.to_csv(output_path, index=False)

    return converted
