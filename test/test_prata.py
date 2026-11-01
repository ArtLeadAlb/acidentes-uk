"""Testes da camada prata (spec na docstring de src/prata.py).

Toda entrada é inventada: CSVs minúsculos escritos dentro de tmp_path.
A saída é lida dos Parquet gravados em data/prata (também dentro de tmp_path).
"""

import csv
import datetime

import duckdb
import pytest

from src import prata

COLUNAS_ACIDENTES = [
    "Accident_Index", "Date", "Time", "Accident_Severity", "Number_of_Vehicles",
    "Number_of_Casualties", "Speed_limit", "Road_Type", "Urban_or_Rural_Area",
    "Light_Conditions", "Weather_Conditions", "Road_Surface_Conditions",
    "Latitude", "Longitude", "Local_Authority_(District)", "InScotland",
]
COLUNAS_VEICULOS = [
    "Accident_Index", "Vehicle_Reference", "Vehicle_Type", "make",
    "Propulsion_Code", "Age_of_Vehicle", "Engine_Capacity_.CC.",
    "Sex_of_Driver", "Age_Band_of_Driver", "Vehicle_Manoeuvre",
    "X1st_Point_of_Impact",
]


def _acidente(**campos):
    """Acidente válido; cada teste sobrescreve só o campo que quer provar."""
    linha = {
        "Accident_Index": "A1", "Date": "2005-01-04", "Time": "17:42",
        "Accident_Severity": "Slight", "Number_of_Vehicles": "2",
        "Number_of_Casualties": "1", "Speed_limit": "30",
        "Road_Type": "Single carriageway", "Urban_or_Rural_Area": "Urban",
        "Light_Conditions": "Daylight", "Weather_Conditions": "Fine no high winds",
        "Road_Surface_Conditions": "Dry", "Latitude": "51.5", "Longitude": "-0.19",
        "Local_Authority_(District)": "Kensington and Chelsea", "InScotland": "No",
    }
    linha.update(campos)
    return linha


def _veiculo(**campos):
    linha = {
        "Accident_Index": "A1", "Vehicle_Reference": "1", "Vehicle_Type": "Car",
        "make": "FORD", "Propulsion_Code": "Petrol", "Age_of_Vehicle": "3.0",
        "Engine_Capacity_.CC.": "1588.0", "Sex_of_Driver": "Male",
        "Age_Band_of_Driver": "26 - 35", "Vehicle_Manoeuvre": "Going ahead other",
        "X1st_Point_of_Impact": "Front",
    }
    linha.update(campos)
    return linha


def _escrever_csv(caminho, colunas, linhas):
    with open(caminho, "w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=colunas)
        escritor.writeheader()
        escritor.writerows(linhas)


def _preparar(tmp_path, monkeypatch, acidentes, veiculos):
    """Cria data/bronze dentro de tmp_path e aponta o código para lá."""
    monkeypatch.chdir(tmp_path)
    bronze = tmp_path / "data" / "bronze"
    bronze.mkdir(parents=True, exist_ok=True)
    _escrever_csv(bronze / "Accident_Information.csv", COLUNAS_ACIDENTES, acidentes)
    _escrever_csv(bronze / "Vehicle_Information.csv", COLUNAS_VEICULOS, veiculos)
    return bronze


def _consultar(sql):
    """Roda a consulta sobre os Parquet gravados em data/prata."""
    con = duckdb.connect()
    con.execute("CREATE SCHEMA prata")
    for nome in ("acidentes", "veiculos"):
        con.execute(f"CREATE VIEW prata.{nome} AS SELECT * FROM read_parquet('data/prata/{nome}.parquet')")
    linhas = con.execute(sql).fetchall()
    con.close()
    return linhas


def test_csv_vira_tabela_com_as_mesmas_linhas(tmp_path, monkeypatch):
    _preparar(
        tmp_path, monkeypatch,
        acidentes=[
            _acidente(Accident_Index="A1"),  # acidente com dois veículos
            _acidente(Accident_Index="A2"),  # acidente com um veículo
        ],
        veiculos=[
            _veiculo(Accident_Index="A1", Vehicle_Reference="1"),
            _veiculo(Accident_Index="A1", Vehicle_Reference="2"),
            _veiculo(Accident_Index="A2", Vehicle_Reference="1"),
        ],
    )

    prata.executar()

    assert _consultar("SELECT COUNT(*) FROM prata.acidentes") == [(2,)]
    assert _consultar("SELECT COUNT(*) FROM prata.veiculos") == [(3,)]


def test_duplicata_exata_sai(tmp_path, monkeypatch):
    _preparar(
        tmp_path, monkeypatch,
        acidentes=[_acidente(), _acidente()],  # linha duplicada idêntica
        veiculos=[_veiculo(), _veiculo()],  # linha duplicada idêntica
    )

    prata.executar()

    assert _consultar("SELECT COUNT(*) FROM prata.acidentes") == [(1,)]
    assert _consultar("SELECT COUNT(*) FROM prata.veiculos") == [(1,)]


def test_mesma_chave_com_conteudo_diferente_encerra(tmp_path, monkeypatch):
    _preparar(
        tmp_path, monkeypatch,
        # mesmo id, gravidade diferente: não é duplicata exata
        acidentes=[_acidente(Accident_Severity="Slight"), _acidente(Accident_Severity="Fatal")],
        veiculos=[_veiculo()],
    )

    with pytest.raises(SystemExit):
        prata.executar()


def test_data_vira_date_e_hora_vira_time(tmp_path, monkeypatch):
    _preparar(
        tmp_path, monkeypatch,
        acidentes=[_acidente(Date="2005-01-04", Time="17:42")],
        veiculos=[_veiculo()],
    )

    prata.executar()

    assert _consultar("SELECT typeof(data_acidente), typeof(hora_acidente) FROM prata.acidentes") == [("DATE", "TIME")]
    assert _consultar("SELECT data_acidente, hora_acidente FROM prata.acidentes") == [
        (datetime.date(2005, 1, 4), datetime.time(17, 42))
    ]


def test_numeros_viram_tipos_numericos(tmp_path, monkeypatch):
    _preparar(
        tmp_path, monkeypatch,
        acidentes=[_acidente(Number_of_Casualties="3", Latitude="51.5")],
        veiculos=[_veiculo(Age_of_Vehicle="3.0", **{"Engine_Capacity_.CC.": "1588.0"})],
    )

    prata.executar()

    assert _consultar(
        "SELECT typeof(num_vitimas), typeof(limite_velocidade), typeof(latitude) FROM prata.acidentes"
    ) == [("INTEGER", "INTEGER", "DOUBLE")]
    assert _consultar(
        "SELECT typeof(idade_veiculo), typeof(cilindrada_cc), idade_veiculo, cilindrada_cc FROM prata.veiculos"
    ) == [("INTEGER", "INTEGER", 3, 1588)]


def test_data_que_nao_converte_encerra_sem_virar_nulo(tmp_path, monkeypatch):
    _preparar(
        tmp_path, monkeypatch,
        acidentes=[_acidente(Date="ontem")],  # texto que não é data
        veiculos=[_veiculo()],
    )

    with pytest.raises(SystemExit):
        prata.executar()


def test_numero_que_nao_converte_encerra_sem_virar_nulo(tmp_path, monkeypatch):
    _preparar(
        tmp_path, monkeypatch,
        acidentes=[_acidente()],
        veiculos=[_veiculo(Age_of_Vehicle="velho")],  # texto que não é número
    )

    with pytest.raises(SystemExit):
        prata.executar()


def test_falha_deixa_a_prata_como_estava(tmp_path, monkeypatch):
    bronze = _preparar(tmp_path, monkeypatch, acidentes=[_acidente()], veiculos=[_veiculo()])
    prata.executar()

    # segunda carga com data inválida: deve falhar sem tocar nas tabelas
    _escrever_csv(bronze / "Accident_Information.csv", COLUNAS_ACIDENTES,
                  [_acidente(Accident_Index="A9", Date="ontem"), _acidente(Accident_Index="A8")])
    with pytest.raises(SystemExit):
        prata.executar()

    assert _consultar("SELECT id_acidente FROM prata.acidentes") == [("A1",)]


def test_sentinela_e_codigos_sem_descricao_viram_nulo(tmp_path, monkeypatch):
    _preparar(
        tmp_path, monkeypatch,
        acidentes=[_acidente(
            Weather_Conditions="Data missing or out of range",  # sentinela
            Urban_or_Rural_Area="Unallocated",  # área não alocada
        )],
        veiculos=[_veiculo(
            Vehicle_Type="109",  # código numérico sem descrição
            Sex_of_Driver="Not known",  # sexo não informado
            Age_Band_of_Driver="Data missing or out of range",  # sentinela
        )],
    )

    prata.executar()

    assert _consultar("SELECT condicao_clima, area FROM prata.acidentes") == [(None, None)]
    assert _consultar(
        "SELECT tipo_veiculo, sexo_condutor, faixa_etaria_condutor FROM prata.veiculos"
    ) == [(None, None, None)]


def test_na_do_csv_vira_nulo_em_texto_numero_e_booleano(tmp_path, monkeypatch):
    _preparar(
        tmp_path, monkeypatch,
        acidentes=[_acidente(
            Latitude="NA", Longitude="NA",  # sem coordenadas registradas
            InScotland="NA",  # sem indicação de Escócia
        )],
        veiculos=[_veiculo(
            Age_of_Vehicle="NA", Propulsion_Code="NA",  # idade e combustível ausentes
            **{"Engine_Capacity_.CC.": "NA"},  # cilindrada ausente
        )],
    )

    prata.executar()

    assert _consultar("SELECT latitude, longitude, em_escocia FROM prata.acidentes") == [(None, None, None)]
    assert _consultar(
        "SELECT idade_veiculo, combustivel, cilindrada_cc FROM prata.veiculos"
    ) == [(None, None, None)]


def test_hora_nula_fica_nula(tmp_path, monkeypatch):
    _preparar(
        tmp_path, monkeypatch,
        acidentes=[_acidente(Time="")],  # acidente sem hora registrada
        veiculos=[_veiculo()],
    )

    prata.executar()

    assert _consultar("SELECT hora_acidente FROM prata.acidentes") == [(None,)]


def test_gravidade_e_traduzida(tmp_path, monkeypatch):
    _preparar(
        tmp_path, monkeypatch,
        acidentes=[
            _acidente(Accident_Index="A1", Accident_Severity="Slight"),
            _acidente(Accident_Index="A2", Accident_Severity="Serious"),
            _acidente(Accident_Index="A3", Accident_Severity="Fatal"),
        ],
        veiculos=[_veiculo()],
    )

    prata.executar()

    assert _consultar("SELECT id_acidente, gravidade FROM prata.acidentes ORDER BY id_acidente") == [
        ("A1", "Leve"), ("A2", "Grave"), ("A3", "Fatal"),
    ]


def test_gravidade_desconhecida_encerra(tmp_path, monkeypatch):
    _preparar(
        tmp_path, monkeypatch,
        acidentes=[_acidente(Accident_Severity="Catastrophic")],  # fora do domínio
        veiculos=[_veiculo()],
    )

    with pytest.raises(SystemExit):
        prata.executar()


def test_em_escocia_vira_booleano(tmp_path, monkeypatch):
    _preparar(
        tmp_path, monkeypatch,
        acidentes=[
            _acidente(Accident_Index="A1", InScotland="Yes"),
            _acidente(Accident_Index="A2", InScotland="No"),
        ],
        veiculos=[_veiculo()],
    )

    prata.executar()

    assert _consultar("SELECT id_acidente, em_escocia FROM prata.acidentes ORDER BY id_acidente") == [
        ("A1", True), ("A2", False),
    ]


def test_arquivo_faltando_encerra_e_nao_cria_a_pasta_da_prata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # sem data/bronze

    with pytest.raises(SystemExit):
        prata.executar()

    assert not (tmp_path / "data" / "prata").exists()


def test_coluna_ausente_no_csv_encerra(tmp_path, monkeypatch):
    bronze = _preparar(tmp_path, monkeypatch, acidentes=[_acidente()], veiculos=[_veiculo()])
    # CSV de acidentes sem a coluna Speed_limit
    sem_limite = [c for c in COLUNAS_ACIDENTES if c != "Speed_limit"]
    linha = {k: v for k, v in _acidente().items() if k != "Speed_limit"}
    _escrever_csv(bronze / "Accident_Information.csv", sem_limite, [linha])

    with pytest.raises(SystemExit):
        prata.executar()


def test_csv_so_com_cabecalho_encerra(tmp_path, monkeypatch):
    _preparar(tmp_path, monkeypatch, acidentes=[], veiculos=[_veiculo()])

    with pytest.raises(SystemExit):
        prata.executar()


def test_rodar_duas_vezes_da_o_mesmo_resultado(tmp_path, monkeypatch):
    _preparar(
        tmp_path, monkeypatch,
        acidentes=[_acidente(Accident_Index="A1"), _acidente(Accident_Index="A2")],
        veiculos=[_veiculo(Accident_Index="A1"), _veiculo(Accident_Index="A2")],
    )

    prata.executar()
    primeira = _consultar("SELECT * FROM prata.acidentes ORDER BY id_acidente")
    prata.executar()
    segunda = _consultar("SELECT * FROM prata.acidentes ORDER BY id_acidente")

    assert primeira == segunda
    assert len(primeira) == 2


def test_csvs_da_bronze_nao_sao_alterados(tmp_path, monkeypatch):
    bronze = _preparar(tmp_path, monkeypatch, acidentes=[_acidente()], veiculos=[_veiculo()])
    antes = [(bronze / n).read_bytes() for n in ("Accident_Information.csv", "Vehicle_Information.csv")]

    prata.executar()

    depois = [(bronze / n).read_bytes() for n in ("Accident_Information.csv", "Vehicle_Information.csv")]
    assert antes == depois


def test_saida_e_gravada_em_parquet_na_pasta_da_prata(tmp_path, monkeypatch):
    _preparar(tmp_path, monkeypatch, acidentes=[_acidente()], veiculos=[_veiculo()])

    prata.executar()

    assert (tmp_path / "data" / "prata" / "acidentes.parquet").is_file()
    assert (tmp_path / "data" / "prata" / "veiculos.parquet").is_file()
