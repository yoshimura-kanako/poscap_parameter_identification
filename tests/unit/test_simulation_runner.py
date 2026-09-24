"""粒子発生シミュレーションワークフローのユニットテスト(MockRockyClient使用)。"""

from pathlib import Path

import pytest

from poscap_calibration.rocky.mock_client import MockRockyClient
from poscap_calibration.rocky.simulation_runner import (
    prepare_filling_input,
    run_particle_generation,
)

DISTRIBUTION_CSV = (
    Path(__file__).parents[2] / "input" / "particle_distribution" / "test_distribution.csv"
)
RAW_CSV = (
    Path(__file__).parents[1]
    / "reference_data"
    / "shear_condition_01"
    / "particle_generation_inlet_raw.csv"
)


def _create_generate_template(tmp_path: Path, name: str) -> Path:
    template_path = tmp_path / "templates" / name
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text("template", encoding="utf-8")
    return template_path


def test_run_particle_generation_orchestrates_client_calls(tmp_path: Path) -> None:
    particles_source = tmp_path / "first_20deg_raw.csv"
    particles_source.write_text("x,y,z,size\n0.001,0.002,0.003,0.0001\n", encoding="utf-8")

    template_path = _create_generate_template(tmp_path, "Generate_Particle.rocky")
    client = MockRockyClient(completed=True, particles_csv=particles_source)
    output_csv = tmp_path / "output" / "particle_generation_inlet_raw.csv"

    result = run_particle_generation(
        client,
        DISTRIBUTION_CSV,
        template_project_path=template_path,
        work_project_path=tmp_path / "work" / "generate.rocky",
        user_process_name="First_20deg",
        output_csv_path=output_csv,
    )

    assert result == output_csv
    assert output_csv.read_text(encoding="utf-8") == particles_source.read_text(encoding="utf-8")
    assert (tmp_path / "work" / "generate.rocky").is_file()
    assert template_path.read_text(encoding="utf-8") == "template"

    call_names = [name for name, _ in client.calls]
    assert call_names == [
        "connect",
        "open_project",
        "delete_results",
        "set_particle_property",
        "save_project_as",
        "run_simulation",
        "export_user_process_particles",
        "disconnect",
    ]

    _, (property_name, distribution_value) = client.calls[3]
    assert property_name == "size_distribution"
    assert distribution_value[0][0] == pytest.approx(289.69)
    assert distribution_value[0][1] == pytest.approx(100.0)

    _, (user_process_name, time_step) = client.calls[6]
    assert user_process_name == "First_20deg"
    assert time_step == 0


def test_run_particle_generation_raises_when_not_completed(tmp_path: Path) -> None:
    client = MockRockyClient(completed=False)
    template_path = _create_generate_template(tmp_path, "Generate_Particle.rocky")

    with pytest.raises(RuntimeError):
        run_particle_generation(
            client,
            DISTRIBUTION_CSV,
            template_project_path=template_path,
            work_project_path=tmp_path / "work" / "generate.rocky",
            user_process_name="First_20deg",
            output_csv_path=tmp_path / "output.csv",
        )

    call_names = [name for name, _ in client.calls]
    assert call_names[-1] == "disconnect"


def _create_template_project(tmp_path: Path) -> Path:
    template_path = tmp_path / "templates" / "Filling.rocky"
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text("template", encoding="utf-8")

    files_dir = tmp_path / "templates" / "Filling.rocky.files"
    files_dir.mkdir()
    (files_dir / "data.bin").write_text("data", encoding="utf-8")
    (files_dir / "Filling.rocky.lock").write_text("lock", encoding="utf-8")

    return template_path


def test_prepare_filling_input_copies_template_and_sets_inlet(tmp_path: Path) -> None:
    template_path = _create_template_project(tmp_path)
    work_path = tmp_path / "work" / "Filling.rocky"
    converted_csv = tmp_path / "results" / "particle_generation_inlet.csv"

    client = MockRockyClient()

    result = prepare_filling_input(
        client,
        RAW_CSV,
        template_project_path=template_path,
        work_project_path=work_path,
        converted_csv_path=converted_csv,
    )

    assert result == work_path
    assert work_path.is_file()
    assert (tmp_path / "work" / "Filling.rocky.files" / "data.bin").is_file()
    assert not (tmp_path / "work" / "Filling.rocky.files" / "Filling.rocky.lock").exists()

    assert converted_csv.is_file()
    assert converted_csv.read_text(encoding="utf-8").splitlines()[0] == "x,y,z,size"

    # 原本が変更されていないこと。
    assert template_path.read_text(encoding="utf-8") == "template"

    call_names = [name for name, _ in client.calls]
    assert call_names == [
        "connect",
        "open_project",
        "set_custom_inlet_csv",
        "save_project_as",
        "disconnect",
    ]
    assert "run_simulation" not in call_names

    _, (inlet_csv_path,) = client.calls[2]
    assert inlet_csv_path == converted_csv


def test_prepare_filling_input_raises_when_template_missing(tmp_path: Path) -> None:
    client = MockRockyClient()

    with pytest.raises(FileNotFoundError):
        prepare_filling_input(
            client,
            RAW_CSV,
            template_project_path=tmp_path / "missing.rocky",
            work_project_path=tmp_path / "work" / "Filling.rocky",
            converted_csv_path=tmp_path / "results" / "inlet.csv",
        )

    assert client.calls == []
