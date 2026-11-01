"""Camada prata: limpeza, tipagem e deduplicação dos CSVs da bronze.

SPEC
Lê Accident_Information.csv e Vehicle_Information.csv de data/bronze (somente
leitura) e grava data/prata/acidentes.parquet e data/prata/veiculos.parquet.
Todo o processamento e as validações acontecem em memória; os arquivos só são
gravados (e substituem os anteriores) se tudo passar.

prata.acidentes (uma linha por acidente):
  id_acidente, data_acidente DATE, hora_acidente TIME, gravidade,
  num_veiculos INTEGER, num_vitimas INTEGER, limite_velocidade INTEGER,
  tipo_via, area, condicao_luz, condicao_clima, condicao_pista,
  latitude DOUBLE, longitude DOUBLE, distrito, em_escocia BOOLEAN
prata.veiculos (uma linha por veículo de um acidente):
  id_acidente, ref_veiculo INTEGER, tipo_veiculo, marca, combustivel,
  idade_veiculo INTEGER, cilindrada_cc INTEGER, sexo_condutor,
  faixa_etaria_condutor, manobra, ponto_impacto

Regras de limpeza:
  - texto vazio, o texto 'NA' (nulo do CSV) e o texto
    'Data missing or out of range' viram NULL;
  - gravidade: Slight -> Leve, Serious -> Grave, Fatal -> Fatal;
  - area 'Unallocated' e sexo 'Not known' viram NULL;
  - tipo_veiculo composto só de dígitos (código sem descrição) vira NULL;
  - InScotland: Yes/No viram BOOLEAN.

CRITÉRIOS DE ACEITE
- Cada CSV vira tabela com as mesmas linhas (após tirar duplicatas exatas).
- Arquivo faltando na bronze encerra com SystemExit, sem criar data/prata.
- Coluna esperada ausente no CSV encerra com SystemExit.
- Duplicata exata sai; a mesma chave com conteúdo diferente encerra.
- Data vira DATE, hora vira TIME, contagens viram INTEGER, coordenadas DOUBLE.
- 'NA' e texto vazio viram NULL em qualquer coluna, inclusive nas numéricas.
- Valor que não converte encerra com SystemExit, sem virar nulo.
- Gravidade fora de Slight/Serious/Fatal encerra com SystemExit.
- Tabela vazia encerra com SystemExit.
- Em qualquer encerramento, prata fica exatamente como estava antes.
- Rodar duas vezes seguidas dá o mesmo resultado.
- Os CSVs da bronze não são alterados.
"""

import sys

import duckdb

from src.config import ARQUIVO_ACIDENTES, ARQUIVO_VEICULOS, BRONZE_DIR, PRATA_DIR

SENTINELA = "Data missing or out of range"
# o CSV escreve o nulo como texto vazio ou como a string NA
NULOS = "['', 'NA']"
GRAVIDADE = {"Fatal": "'Fatal'", "Serious": "'Grave'", "Slight": "'Leve'"}
SIM_NAO = {"Yes": "TRUE", "No": "FALSE"}


class ErroPrata(Exception):
    """Violação de uma regra da prata: a transação é desfeita."""


def _literal(caminho) -> str:
    return str(caminho).replace("'", "''")


def _texto(coluna: str) -> str:
    return f"""NULLIF(NULLIF(TRIM("{coluna}"), ''), '{SENTINELA}')"""


def _mapear(coluna: str, mapa: dict[str, str]) -> str:
    """Traduz valores conhecidos; valor desconhecido derruba a consulta."""
    casos = " ".join(f"""WHEN "{coluna}" = '{k}' THEN {v}""" for k, v in mapa.items())
    return (
        f"""CASE WHEN "{coluna}" IS NULL THEN NULL {casos} """
        f"""ELSE error('{coluna}: valor desconhecido ' || "{coluna}") END"""
    )


def _inteiro(coluna: str) -> str:
    return f'CAST("{coluna}" AS INTEGER)'


def _inteiro_via_decimal(coluna: str) -> str:
    # o CSV traz '3.0'; o CAST direto de texto com ponto para INTEGER falha
    return f'CAST(CAST("{coluna}" AS DOUBLE) AS INTEGER)'


def _decimal(coluna: str) -> str:
    return f'CAST("{coluna}" AS DOUBLE)'


def _sql_acidentes() -> str:
    arquivo = _literal(BRONZE_DIR / ARQUIVO_ACIDENTES)
    return f"""
    CREATE OR REPLACE TABLE prata.acidentes AS
    SELECT DISTINCT
        "Accident_Index" AS id_acidente,
        CAST("Date" AS DATE) AS data_acidente,
        CAST("Time" AS TIME) AS hora_acidente,
        {_mapear("Accident_Severity", GRAVIDADE)} AS gravidade,
        {_inteiro("Number_of_Vehicles")} AS num_veiculos,
        {_inteiro("Number_of_Casualties")} AS num_vitimas,
        {_inteiro("Speed_limit")} AS limite_velocidade,
        {_texto("Road_Type")} AS tipo_via,
        NULLIF({_texto("Urban_or_Rural_Area")}, 'Unallocated') AS area,
        {_texto("Light_Conditions")} AS condicao_luz,
        {_texto("Weather_Conditions")} AS condicao_clima,
        {_texto("Road_Surface_Conditions")} AS condicao_pista,
        {_decimal("Latitude")} AS latitude,
        {_decimal("Longitude")} AS longitude,
        {_texto("Local_Authority_(District)")} AS distrito,
        {_mapear("InScotland", SIM_NAO)} AS em_escocia
    FROM read_csv('{arquivo}', header = true, all_varchar = true, nullstr = {NULOS})
    """


def _sql_veiculos() -> str:
    arquivo = _literal(BRONZE_DIR / ARQUIVO_VEICULOS)
    return f"""
    CREATE OR REPLACE TABLE prata.veiculos AS
    SELECT DISTINCT
        "Accident_Index" AS id_acidente,
        {_inteiro("Vehicle_Reference")} AS ref_veiculo,
        CASE WHEN regexp_matches(TRIM("Vehicle_Type"), '^[0-9]+$') THEN NULL
             ELSE {_texto("Vehicle_Type")} END AS tipo_veiculo,
        {_texto("make")} AS marca,
        {_texto("Propulsion_Code")} AS combustivel,
        {_inteiro_via_decimal("Age_of_Vehicle")} AS idade_veiculo,
        {_inteiro_via_decimal("Engine_Capacity_.CC.")} AS cilindrada_cc,
        NULLIF({_texto("Sex_of_Driver")}, 'Not known') AS sexo_condutor,
        {_texto("Age_Band_of_Driver")} AS faixa_etaria_condutor,
        {_texto("Vehicle_Manoeuvre")} AS manobra,
        {_texto("X1st_Point_of_Impact")} AS ponto_impacto
    FROM read_csv('{arquivo}', header = true, all_varchar = true, nullstr = {NULOS})
    """


def _verificar(con, tabela: str, chave: list[str]) -> int:
    total = con.execute(f"SELECT COUNT(*) FROM prata.{tabela}").fetchone()[0]
    if total == 0:
        raise ErroPrata(f"prata.{tabela} ficou vazia")
    colunas = ", ".join(chave)
    repetidas = con.execute(
        f"SELECT COUNT(*) FROM (SELECT {colunas} FROM prata.{tabela} "
        f"GROUP BY {colunas} HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    if repetidas:
        raise ErroPrata(
            f"prata.{tabela}: {repetidas} chave(s) repetida(s) com conteúdo diferente"
        )
    return total


def executar() -> None:
    for nome in (ARQUIVO_ACIDENTES, ARQUIVO_VEICULOS):
        if not (BRONZE_DIR / nome).is_file():
            sys.exit(f"Falta {BRONZE_DIR / nome}. Rode a bronze antes.")

    con = duckdb.connect()  # em memória: nada é gravado antes de tudo passar
    try:
        con.execute("CREATE SCHEMA prata")
        con.execute(_sql_acidentes())
        con.execute(_sql_veiculos())
        n_acidentes = _verificar(con, "acidentes", ["id_acidente"])
        n_veiculos = _verificar(con, "veiculos", ["id_acidente", "ref_veiculo"])
    except (duckdb.Error, ErroPrata) as erro:
        con.close()
        sys.exit(f"Prata cancelada, nada foi alterado: {erro}")

    PRATA_DIR.mkdir(parents=True, exist_ok=True)
    for nome, ordem in (("acidentes", "id_acidente"), ("veiculos", "id_acidente, ref_veiculo")):
        destino = _literal(PRATA_DIR / f"{nome}.parquet")
        con.execute(
            f"COPY (SELECT * FROM prata.{nome} ORDER BY {ordem}) TO '{destino}' (FORMAT parquet)"
        )
    con.close()
    print(f"prata/acidentes.parquet: {n_acidentes} linhas")
    print(f"prata/veiculos.parquet: {n_veiculos} linhas")


if __name__ == "__main__":
    executar()
