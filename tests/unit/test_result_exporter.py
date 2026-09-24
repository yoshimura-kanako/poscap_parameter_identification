"""Particle Custom Inlet CSV変換(FR-08)のユニットテスト。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from poscap_calibration.rocky.result_exporter import (
    ParticleCustomInletConversionError,
    convert_particle_custom_inlet,
    convert_particle_custom_inlet_csv,
)

REFERENCE_DIR = (
    Path(__file__).parents[1] / "reference_data" / "shear_condition_01"
)
RAW_CSV = REFERENCE_DIR / "particle_generation_inlet_raw.csv"


def test_convert_particle_custom_inlet_selects_columns_by_keyword() -> None:
    raw = pd.read_csv(RAW_CSV)

    converted = convert_particle_custom_inlet(raw)

    assert list(converted.columns) == ["x", "y", "z", "size"]
    assert len(converted) == len(raw)
    assert converted["x"].tolist() == raw.iloc[:, 1].tolist()
    assert converted["y"].tolist() == raw.iloc[:, 2].tolist()
    assert converted["z"].tolist() == raw.iloc[:, 3].tolist()
    assert converted["size"].tolist() == raw.iloc[:, 4].tolist()


def test_convert_particle_custom_inlet_csv_writes_expected_header(tmp_path: Path) -> None:
    output_path = tmp_path / "particle_generation_inlet.csv"

    convert_particle_custom_inlet_csv(RAW_CSV, output_path)

    header = output_path.read_text(encoding="utf-8").splitlines()[0]
    assert header == "x,y,z,size"


def test_convert_particle_custom_inlet_missing_column_raises() -> None:
    raw = pd.DataFrame({"Index [<ind>]": [0], "Particle Size [m]": [0.001]})

    with pytest.raises(ParticleCustomInletConversionError):
        convert_particle_custom_inlet(raw)


def test_convert_particle_custom_inlet_ambiguous_column_raises() -> None:
    raw = pd.DataFrame(
        {
            "Coordinate : X [m]": [0.0],
            "Coordinate : X duplicate [m]": [0.0],
            "Coordinate : Y [m]": [0.0],
            "Coordinate : Z [m]": [0.0],
            "Particle Size [m]": [0.001],
        }
    )

    with pytest.raises(ParticleCustomInletConversionError):
        convert_particle_custom_inlet(raw)


def test_convert_particle_custom_inlet_non_positive_size_raises() -> None:
    raw = pd.DataFrame(
        {
            "Coordinate : X [m]": [0.0],
            "Coordinate : Y [m]": [0.0],
            "Coordinate : Z [m]": [0.0],
            "Particle Size [m]": [0.0],
        }
    )

    with pytest.raises(ParticleCustomInletConversionError):
        convert_particle_custom_inlet(raw)
