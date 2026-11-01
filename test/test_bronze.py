"""Testes da camada bronze (spec na docstring de src/bronze.py)."""

from pathlib import Path

import pytest

from src import bronze

CONTEUDO_ACIDENTES = b"Accident_Index,Year\nA1,2005\n"
CONTEUDO_VEICULOS = b"Accident_Index,Vehicle_Reference\nA1,1\n"


def _criar_origem(pasta: Path, com_veiculos: bool = True) -> Path:
    pasta.mkdir(parents=True)
    (pasta / "Accident_Information.csv").write_bytes(CONTEUDO_ACIDENTES)
    if com_veiculos:
        (pasta / "Vehicle_Information.csv").write_bytes(CONTEUDO_VEICULOS)
    return pasta


def test_arquivos_copiados_sao_identicos_aos_da_origem(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    origem = _criar_origem(tmp_path / "origem")

    bronze.executar(origem)

    assert (tmp_path / "data/bronze/Accident_Information.csv").read_bytes() == CONTEUDO_ACIDENTES
    assert (tmp_path / "data/bronze/Vehicle_Information.csv").read_bytes() == CONTEUDO_VEICULOS


def test_arquivos_da_origem_nao_sao_modificados(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    origem = _criar_origem(tmp_path / "origem")

    bronze.executar(origem)

    assert (origem / "Accident_Information.csv").read_bytes() == CONTEUDO_ACIDENTES
    assert (origem / "Vehicle_Information.csv").read_bytes() == CONTEUDO_VEICULOS


def test_arquivo_faltando_encerra_e_nao_cria_a_bronze(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # origem sem Vehicle_Information.csv
    origem = _criar_origem(tmp_path / "origem", com_veiculos=False)

    with pytest.raises(SystemExit):
        bronze.executar(origem)

    assert not (tmp_path / "data/bronze").exists()


def test_sem_origem_usa_a_pasta_baixada_do_kaggle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    baixada = _criar_origem(tmp_path / "cache_kaggle")
    monkeypatch.setattr(bronze, "baixar_dataset", lambda: baixada)

    bronze.executar()

    assert (tmp_path / "data/bronze/Accident_Information.csv").read_bytes() == CONTEUDO_ACIDENTES


def test_rodar_duas_vezes_deixa_o_mesmo_resultado(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    origem = _criar_origem(tmp_path / "origem")

    bronze.executar(origem)
    bronze.executar(origem)

    assert (tmp_path / "data/bronze/Vehicle_Information.csv").read_bytes() == CONTEUDO_VEICULOS


def test_linha_de_comando_aceita_a_origem(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    origem = _criar_origem(tmp_path / "origem")

    bronze.main(["--origem", str(origem)])

    assert (tmp_path / "data/bronze/Accident_Information.csv").is_file()
