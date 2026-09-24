"""粒度分布CSV読込み(FR-03)のユニットテスト。"""

from pathlib import Path

import pytest

from poscap_calibration.particle_distribution import (
    ParticleDistributionError,
    load_particle_distribution,
)

INPUT_CSV = (
    Path(__file__).parents[2] / "input" / "particle_distribution" / "test_distribution.csv"
)


def test_load_particle_distribution_orders_by_descending_size() -> None:
    distribution = load_particle_distribution(INPUT_CSV)

    sizes = [size for size, _ in distribution]
    percentages = [percentage for _, percentage in distribution]
    assert sizes == sorted(sizes, reverse=True)
    assert sizes == pytest.approx(
        [289.69, 211.798, 185.834, 159.87, 133.906, 107.942, 81.978, 56.01, 30.05]
    )
    assert percentages == pytest.approx(
        [100.0, 85.6, 81.73, 73.33, 57.81, 42.01, 27.54, 11.62, 1.0e-20]
    )
    assert distribution[0][1] == pytest.approx(100.0)


def test_load_particle_distribution_rejects_non_monotonic_percent(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad_distribution.csv"
    csv_path.write_text(
        "particle_size,cumulative_mass_percent\n40,100\n20,30\n10,50\n",
        encoding="utf-8",
    )

    with pytest.raises(ParticleDistributionError):
        load_particle_distribution(csv_path)


def test_load_particle_distribution_rejects_max_not_100(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad_distribution.csv"
    csv_path.write_text(
        "particle_size,cumulative_mass_percent\n40,90\n20,50\n10,10\n",
        encoding="utf-8",
    )

    with pytest.raises(ParticleDistributionError):
        load_particle_distribution(csv_path)


def test_load_particle_distribution_rejects_non_positive_size(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad_distribution.csv"
    csv_path.write_text(
        "particle_size,cumulative_mass_percent\n0,50\n10,100\n",
        encoding="utf-8",
    )

    with pytest.raises(ParticleDistributionError):
        load_particle_distribution(csv_path)
