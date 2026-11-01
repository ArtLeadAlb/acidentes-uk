"""Testes da camada ouro (spec na docstring de src/ouro.py).

As tabelas da prata são criadas e preenchidas pelo próprio teste e gravadas
como Parquet em data/prata, dentro de tmp_path. Nada é lido do data/ do projeto.
"""

import datetime
import pathlib

import duckdb
import pytest

from src import ouro

DATA = datetime.date(2005, 1, 4)  # terça-feira
TABELAS_OURO = ouro.TABELAS_OURO


def _banco(tmp_path, monkeypatch):
    """Banco em memória com as tabelas da prata, vazias."""
    monkeypatch.chdir(tmp_path)
    con = duckdb.connect()
    con.execute("CREATE SCHEMA prata")
    con.execute(
        """CREATE TABLE prata.acidentes (
            id_acidente VARCHAR, data_acidente DATE, hora_acidente TIME,
            gravidade VARCHAR, num_veiculos INTEGER, num_vitimas INTEGER,
            limite_velocidade INTEGER, tipo_via VARCHAR, area VARCHAR,
            condicao_luz VARCHAR, condicao_clima VARCHAR, condicao_pista VARCHAR,
            latitude DOUBLE, longitude DOUBLE, distrito VARCHAR, em_escocia BOOLEAN)"""
    )
    con.execute(
        """CREATE TABLE prata.veiculos (
            id_acidente VARCHAR, ref_veiculo INTEGER, tipo_veiculo VARCHAR,
            marca VARCHAR, combustivel VARCHAR, idade_veiculo INTEGER,
            cilindrada_cc INTEGER, sexo_condutor VARCHAR,
            faixa_etaria_condutor VARCHAR, manobra VARCHAR, ponto_impacto VARCHAR)"""
    )
    return con


def _gravar_prata(con):
    """Grava as tabelas inventadas em data/prata e fecha o banco em memória."""
    pathlib.Path("data/prata").mkdir(parents=True, exist_ok=True)
    for nome in ("acidentes", "veiculos"):
        con.execute(f"COPY prata.{nome} TO 'data/prata/{nome}.parquet' (FORMAT parquet)")
    con.close()


def _acidente(con, id_acidente, data=DATA, hora=datetime.time(10, 0), gravidade="Leve", vitimas=1):
    con.execute(
        "INSERT INTO prata.acidentes (id_acidente, data_acidente, hora_acidente, gravidade, num_vitimas) "
        "VALUES (?, ?, ?, ?, ?)",
        [id_acidente, data, hora, gravidade, vitimas],
    )


def _veiculo(con, id_acidente, ref=1, tipo="Car", idade=3):
    con.execute(
        "INSERT INTO prata.veiculos (id_acidente, ref_veiculo, tipo_veiculo, idade_veiculo) "
        "VALUES (?, ?, ?, ?)",
        [id_acidente, ref, tipo, idade],
    )


def _consultar(sql):
    """Roda a consulta sobre os Parquet gravados em data/ouro."""
    con = duckdb.connect()
    con.execute("CREATE SCHEMA ouro")
    for nome in TABELAS_OURO:
        con.execute(f"CREATE VIEW ouro.{nome} AS SELECT * FROM read_parquet('data/ouro/{nome}.parquet')")
    linhas = con.execute(sql).fetchall()
    con.close()
    return linhas


def test_acidente_com_dois_veiculos_conta_uma_vez(tmp_path, monkeypatch):
    con = _banco(tmp_path, monkeypatch)
    _acidente(con, "A1", vitimas=3)  # um acidente, três vítimas
    _veiculo(con, "A1", ref=1)  # primeiro veículo do acidente
    _veiculo(con, "A1", ref=2)  # segundo veículo do mesmo acidente
    _gravar_prata(con)

    ouro.executar()

    assert _consultar("SELECT COUNT(*) FROM ouro.acidentes_veiculos") == [(2,)]
    assert _consultar("SELECT veiculos, acidentes FROM ouro.indicador_periodo_dia") == [(2, 1)]
    assert _consultar("SELECT acidentes, vitimas FROM ouro.indicador_mensal") == [(1, 3)]


def test_veiculo_sem_acidente_e_acidente_sem_veiculo_ficam_fora(tmp_path, monkeypatch):
    con = _banco(tmp_path, monkeypatch)
    _acidente(con, "A1")  # acidente com veículo: entra
    _veiculo(con, "A1")
    _acidente(con, "A2")  # acidente sem nenhum veículo: fica fora
    _veiculo(con, "ORFAO")  # veículo cujo acidente não existe: fica fora
    _gravar_prata(con)

    ouro.executar()

    assert _consultar("SELECT id_acidente FROM ouro.acidentes_veiculos") == [("A1",)]


def test_periodo_do_dia_nas_fronteiras(tmp_path, monkeypatch):
    con = _banco(tmp_path, monkeypatch)
    horas = {
        "A1": datetime.time(5, 59),   # última hora da madrugada
        "A2": datetime.time(6, 0),    # primeira da manhã
        "A3": datetime.time(11, 59),  # última da manhã
        "A4": datetime.time(12, 0),   # primeira da tarde
        "A5": datetime.time(17, 59),  # última da tarde
        "A6": datetime.time(18, 0),   # primeira da noite
        "A7": datetime.time(23, 59),  # última da noite
        "A8": None,                   # hora não registrada
    }
    for id_acidente, hora in horas.items():
        _acidente(con, id_acidente, hora=hora)
        _veiculo(con, id_acidente)
    _gravar_prata(con)

    ouro.executar()

    assert _consultar(
        "SELECT id_acidente, periodo_dia FROM ouro.acidentes_veiculos ORDER BY id_acidente"
    ) == [
        ("A1", "Madrugada"), ("A2", "Manhã"), ("A3", "Manhã"), ("A4", "Tarde"),
        ("A5", "Tarde"), ("A6", "Noite"), ("A7", "Noite"), ("A8", "Não informado"),
    ]


def test_faixa_de_idade_do_veiculo_nas_fronteiras(tmp_path, monkeypatch):
    con = _banco(tmp_path, monkeypatch)
    idades = {"A1": 2, "A2": 3, "A3": 5, "A4": 6, "A5": 10, "A6": 11, "A7": None}
    for id_acidente, idade in idades.items():
        _acidente(con, id_acidente)
        _veiculo(con, id_acidente, idade=idade)
    _gravar_prata(con)

    ouro.executar()

    assert _consultar(
        "SELECT id_acidente, faixa_idade_veiculo FROM ouro.acidentes_veiculos ORDER BY id_acidente"
    ) == [
        ("A1", "0-2 anos"), ("A2", "3-5 anos"), ("A3", "3-5 anos"), ("A4", "6-10 anos"),
        ("A5", "6-10 anos"), ("A6", "11+ anos"), ("A7", "Não informado"),
    ]


def test_tipo_de_veiculo_nulo_vira_nao_informado(tmp_path, monkeypatch):
    con = _banco(tmp_path, monkeypatch)
    _acidente(con, "A1")
    _veiculo(con, "A1", tipo=None)  # tipo sem descrição na prata
    _gravar_prata(con)

    ouro.executar()

    assert _consultar("SELECT tipo_veiculo FROM ouro.indicador_tipo_veiculo") == [("Não informado",)]


def test_sabado_e_domingo_sao_fim_de_semana(tmp_path, monkeypatch):
    con = _banco(tmp_path, monkeypatch)
    datas = {
        "A1": datetime.date(2005, 1, 1),  # sábado
        "A2": datetime.date(2005, 1, 2),  # domingo
        "A3": datetime.date(2005, 1, 3),  # segunda
        "A4": datetime.date(2005, 1, 7),  # sexta
    }
    for id_acidente, data in datas.items():
        _acidente(con, id_acidente, data=data)
        _veiculo(con, id_acidente)
    _gravar_prata(con)

    ouro.executar()

    assert _consultar(
        "SELECT id_acidente, fim_de_semana FROM ouro.acidentes_veiculos ORDER BY id_acidente"
    ) == [("A1", True), ("A2", True), ("A3", False), ("A4", False)]


def test_percentual_de_fatais_e_fatais_sobre_acidentes(tmp_path, monkeypatch):
    con = _banco(tmp_path, monkeypatch)
    # quatro acidentes à tarde, um deles fatal: 1 / 4 = 25%
    _acidente(con, "A1", hora=datetime.time(14, 0), gravidade="Fatal")
    _acidente(con, "A2", hora=datetime.time(14, 0), gravidade="Leve")
    _acidente(con, "A3", hora=datetime.time(14, 0), gravidade="Grave")
    _acidente(con, "A4", hora=datetime.time(14, 0), gravidade="Leve")
    for id_acidente in ("A1", "A2", "A3", "A4"):
        _veiculo(con, id_acidente)
    # um acidente fatal de madrugada com dois veículos: 1 / 1 = 100%
    _acidente(con, "A5", hora=datetime.time(3, 0), gravidade="Fatal")
    _veiculo(con, "A5", ref=1)
    _veiculo(con, "A5", ref=2)
    _gravar_prata(con)

    ouro.executar()

    assert _consultar(
        "SELECT periodo_dia, acidentes, acidentes_fatais, pct_fatais "
        "FROM ouro.indicador_periodo_dia ORDER BY ordem"
    ) == [("Madrugada", 1, 1, 100.0), ("Tarde", 4, 1, 25.0)]


def test_indicador_mensal_agrupa_por_ano_e_mes(tmp_path, monkeypatch):
    con = _banco(tmp_path, monkeypatch)
    _acidente(con, "A1", data=datetime.date(2005, 1, 10), vitimas=2)  # janeiro
    _acidente(con, "A2", data=datetime.date(2005, 1, 20), vitimas=1, gravidade="Fatal")  # janeiro
    _acidente(con, "A3", data=datetime.date(2005, 2, 1), vitimas=4)  # fevereiro
    for id_acidente in ("A1", "A2", "A3"):
        _veiculo(con, id_acidente)
    _gravar_prata(con)

    ouro.executar()

    assert _consultar(
        "SELECT ano, mes, mes_referencia, acidentes, acidentes_fatais, vitimas "
        "FROM ouro.indicador_mensal ORDER BY mes"
    ) == [
        (2005, 1, datetime.date(2005, 1, 1), 2, 1, 3),
        (2005, 2, datetime.date(2005, 2, 1), 1, 0, 4),
    ]


def test_indicador_geral_tem_uma_linha_com_os_totais(tmp_path, monkeypatch):
    con = _banco(tmp_path, monkeypatch)
    # A1: fatal, dois veículos, três vítimas
    _acidente(con, "A1", data=datetime.date(2005, 1, 10), gravidade="Fatal", vitimas=3)
    _veiculo(con, "A1", ref=1)
    _veiculo(con, "A1", ref=2)
    # A2: leve, um veículo, uma vítima, em outra data
    _acidente(con, "A2", data=datetime.date(2005, 3, 5), gravidade="Leve", vitimas=1)
    _veiculo(con, "A2")
    _gravar_prata(con)

    ouro.executar()

    assert _consultar(
        "SELECT acidentes, veiculos, acidentes_fatais, pct_fatais, vitimas, data_inicio, data_fim "
        "FROM ouro.indicador_geral"
    ) == [(2, 3, 1, 50.0, 4, datetime.date(2005, 1, 10), datetime.date(2005, 3, 5))]


def test_tabelas_da_ouro_sao_gravadas_em_parquet(tmp_path, monkeypatch):
    con = _banco(tmp_path, monkeypatch)
    _acidente(con, "A1")
    _veiculo(con, "A1")
    _gravar_prata(con)

    ouro.executar()

    for nome in TABELAS_OURO:
        assert (tmp_path / "data" / "ouro" / f"{nome}.parquet").is_file()


def test_sem_parquet_da_prata_encerra_e_nao_cria_a_ouro(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # nada em data/prata

    with pytest.raises(SystemExit):
        ouro.executar()

    assert not (tmp_path / "data" / "ouro").exists()


def test_prata_incompleta_encerra(tmp_path, monkeypatch):
    con = _banco(tmp_path, monkeypatch)
    _acidente(con, "A1")
    _veiculo(con, "A1")
    _gravar_prata(con)
    (tmp_path / "data" / "prata" / "veiculos.parquet").unlink()  # falta um dos dois

    with pytest.raises(SystemExit):
        ouro.executar()


def test_juncao_vazia_encerra_e_deixa_a_ouro_como_estava(tmp_path, monkeypatch):
    con = _banco(tmp_path, monkeypatch)
    _acidente(con, "A1")
    _veiculo(con, "A1")
    _gravar_prata(con)
    ouro.executar()

    con = _banco(tmp_path, monkeypatch)
    _acidente(con, "A1")  # nova prata: acidente sem nenhum veículo, nada casa
    _gravar_prata(con)
    with pytest.raises(SystemExit):
        ouro.executar()

    assert _consultar("SELECT id_acidente FROM ouro.acidentes_veiculos") == [("A1",)]


def test_rodar_duas_vezes_da_o_mesmo_resultado(tmp_path, monkeypatch):
    con = _banco(tmp_path, monkeypatch)
    _acidente(con, "A1", gravidade="Fatal")
    _veiculo(con, "A1", ref=1)
    _veiculo(con, "A1", ref=2, tipo="Van")
    _gravar_prata(con)

    ouro.executar()
    primeira = _consultar("SELECT * FROM ouro.indicador_tipo_veiculo ORDER BY tipo_veiculo")
    ouro.executar()
    segunda = _consultar("SELECT * FROM ouro.indicador_tipo_veiculo ORDER BY tipo_veiculo")

    assert primeira == segunda
    assert len(primeira) == 2
