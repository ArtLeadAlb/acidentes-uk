"""Camada ouro: junta acidentes e veículos numa tabela e gera os indicadores.

SPEC
Lê data/prata/acidentes.parquet e veiculos.parquet e grava em data/ouro um
Parquet por tabela (o nome do arquivo é o nome da tabela abaixo). Tudo é
calculado em memória; os arquivos só são gravados se tudo passar:

ouro.acidentes_veiculos  (tabela única, UMA LINHA POR VEÍCULO)
  JOIN de prata.veiculos com prata.acidentes por id_acidente (INNER JOIN),
  mais as colunas derivadas: ano, mes, fim_de_semana, periodo_dia e
  faixa_idade_veiculo. tipo_veiculo nulo vira 'Não informado'.
  periodo_dia: Madrugada 00h-05h, Manhã 06h-11h, Tarde 12h-17h, Noite
  18h-23h; hora nula vira 'Não informado'.
  faixa_idade_veiculo: '0-2 anos', '3-5 anos', '6-10 anos', '11+ anos';
  idade nula vira 'Não informado'.

Indicadores (o dashboard lê só estas tabelas, sem calcular nada):
  ouro.indicador_periodo_dia, ouro.indicador_tipo_veiculo,
  ouro.indicador_idade_veiculo -> categoria (periodo_dia, tipo_veiculo ou
    faixa_idade_veiculo), veiculos, acidentes, acidentes_fatais, pct_fatais
    (e ordem, quando a categoria tem ordem natural)
  ouro.indicador_mensal -> ano, mes, mes_referencia, acidentes,
    acidentes_fatais, vitimas
  ouro.indicador_geral -> uma linha: acidentes, veiculos, acidentes_fatais,
    pct_fatais, vitimas, data_inicio, data_fim
  pct_fatais = 100 * acidentes_fatais / acidentes, com 2 casas decimais.

CRITÉRIOS DE ACEITE
- Parquet da prata ausente encerra com SystemExit, sem criar data/ouro.
- Veículo sem acidente e acidente sem veículo ficam fora da tabela única.
- Acidente com dois veículos aparece em duas linhas da tabela única, mas conta
  uma vez em acidentes e uma vez em vitimas nos indicadores.
- indicador_geral tem uma única linha, com cada acidente contado uma vez.
- Fronteiras do período do dia: 05:59 Madrugada, 06:00 Manhã, 11:59 Manhã,
  12:00 Tarde, 17:59 Tarde, 18:00 Noite, 23:59 Noite.
- Fronteiras da idade do veículo: 2 -> 0-2, 3 -> 3-5, 5 -> 3-5, 6 -> 6-10,
  10 -> 6-10, 11 -> 11+.
- Sábado e domingo são fim de semana; segunda a sexta não.
- pct_fatais = 100 * fatais / acidentes.
- Junção vazia encerra com SystemExit e data/ouro fica como estava.
- Rodar duas vezes seguidas dá o mesmo resultado.
"""

import sys

import duckdb

from src.config import OURO_DIR, PRATA_DIR

NAO_INFORMADO = "Não informado"

ORDEM_PERIODO = (
    "CASE periodo_dia WHEN 'Madrugada' THEN 1 WHEN 'Manhã' THEN 2 "
    "WHEN 'Tarde' THEN 3 WHEN 'Noite' THEN 4 ELSE 5 END"
)
ORDEM_IDADE = (
    "CASE faixa_idade_veiculo WHEN '0-2 anos' THEN 1 WHEN '3-5 anos' THEN 2 "
    "WHEN '6-10 anos' THEN 3 WHEN '11+ anos' THEN 4 ELSE 5 END"
)

# nome da tabela -> (coluna da categoria, expressão de ordem ou None)
INDICADORES = {
    "indicador_periodo_dia": ("periodo_dia", ORDEM_PERIODO),
    "indicador_tipo_veiculo": ("tipo_veiculo", None),
    "indicador_idade_veiculo": ("faixa_idade_veiculo", ORDEM_IDADE),
}


class ErroOuro(Exception):
    """Violação de uma regra da ouro: a transação é desfeita."""


SQL_TABELA_UNICA = f"""
CREATE OR REPLACE TABLE ouro.acidentes_veiculos AS
SELECT
    a.id_acidente,
    v.ref_veiculo,
    a.data_acidente,
    year(a.data_acidente) AS ano,
    month(a.data_acidente) AS mes,
    isodow(a.data_acidente) >= 6 AS fim_de_semana,
    a.hora_acidente,
    CASE WHEN a.hora_acidente IS NULL THEN '{NAO_INFORMADO}'
         WHEN hour(a.hora_acidente) < 6 THEN 'Madrugada'
         WHEN hour(a.hora_acidente) < 12 THEN 'Manhã'
         WHEN hour(a.hora_acidente) < 18 THEN 'Tarde'
         ELSE 'Noite' END AS periodo_dia,
    a.gravidade,
    a.num_veiculos,
    a.num_vitimas,
    a.limite_velocidade,
    a.tipo_via,
    a.area,
    a.condicao_luz,
    a.condicao_clima,
    a.condicao_pista,
    a.latitude,
    a.longitude,
    a.distrito,
    a.em_escocia,
    COALESCE(v.tipo_veiculo, '{NAO_INFORMADO}') AS tipo_veiculo,
    v.marca,
    v.combustivel,
    v.idade_veiculo,
    CASE WHEN v.idade_veiculo IS NULL THEN '{NAO_INFORMADO}'
         WHEN v.idade_veiculo <= 2 THEN '0-2 anos'
         WHEN v.idade_veiculo <= 5 THEN '3-5 anos'
         WHEN v.idade_veiculo <= 10 THEN '6-10 anos'
         ELSE '11+ anos' END AS faixa_idade_veiculo,
    v.cilindrada_cc,
    v.sexo_condutor,
    v.faixa_etaria_condutor,
    v.manobra,
    v.ponto_impacto
FROM prata.veiculos AS v
INNER JOIN prata.acidentes AS a ON a.id_acidente = v.id_acidente
"""

_FATAIS = "COUNT(DISTINCT id_acidente) FILTER (WHERE gravidade = 'Fatal')"
_PCT = f"ROUND(CAST(100 AS DOUBLE) * {_FATAIS} / COUNT(DISTINCT id_acidente), 2)"


def _sql_indicador(nome: str, categoria: str, ordem: str | None) -> str:
    coluna_ordem = f", {ordem} AS ordem" if ordem else ""
    return f"""
    CREATE OR REPLACE TABLE ouro.{nome} AS
    SELECT
        {categoria}{coluna_ordem},
        COUNT(*) AS veiculos,
        COUNT(DISTINCT id_acidente) AS acidentes,
        {_FATAIS} AS acidentes_fatais,
        {_PCT} AS pct_fatais
    FROM ouro.acidentes_veiculos
    GROUP BY ALL
    """


SQL_INDICADOR_MENSAL = """
CREATE OR REPLACE TABLE ouro.indicador_mensal AS
WITH acidentes AS (
    SELECT DISTINCT id_acidente, ano, mes, gravidade, num_vitimas
    FROM ouro.acidentes_veiculos
)
SELECT
    ano,
    mes,
    make_date(ano, mes, 1) AS mes_referencia,
    COUNT(*) AS acidentes,
    COUNT(*) FILTER (WHERE gravidade = 'Fatal') AS acidentes_fatais,
    CAST(SUM(num_vitimas) AS BIGINT) AS vitimas
FROM acidentes
GROUP BY ano, mes
"""


SQL_INDICADOR_GERAL = """
CREATE OR REPLACE TABLE ouro.indicador_geral AS
WITH acidentes AS (
    SELECT DISTINCT id_acidente, data_acidente, gravidade, num_vitimas
    FROM ouro.acidentes_veiculos
)
SELECT
    COUNT(*) AS acidentes,
    (SELECT COUNT(*) FROM ouro.acidentes_veiculos) AS veiculos,
    COUNT(*) FILTER (WHERE gravidade = 'Fatal') AS acidentes_fatais,
    ROUND(CAST(100 AS DOUBLE) * COUNT(*) FILTER (WHERE gravidade = 'Fatal') / COUNT(*), 2) AS pct_fatais,
    CAST(SUM(num_vitimas) AS BIGINT) AS vitimas,
    MIN(data_acidente) AS data_inicio,
    MAX(data_acidente) AS data_fim
FROM acidentes
"""


TABELAS_OURO = ["acidentes_veiculos", *INDICADORES, "indicador_mensal", "indicador_geral"]


def _literal(caminho) -> str:
    return str(caminho).replace("'", "''")


def executar() -> None:
    entradas = {nome: PRATA_DIR / f"{nome}.parquet" for nome in ("acidentes", "veiculos")}
    for arquivo in entradas.values():
        if not arquivo.is_file():
            sys.exit(f"Falta {arquivo}. Rode a prata antes.")

    con = duckdb.connect()  # em memória: nada é gravado antes de tudo passar
    try:
        con.execute("CREATE SCHEMA prata")
        con.execute("CREATE SCHEMA ouro")
        for nome, arquivo in entradas.items():
            con.execute(
                f"CREATE TABLE prata.{nome} AS SELECT * FROM read_parquet('{_literal(arquivo)}')"
            )
        con.execute(SQL_TABELA_UNICA)
        total = con.execute("SELECT COUNT(*) FROM ouro.acidentes_veiculos").fetchone()[0]
        if total == 0:
            raise ErroOuro("nenhum veículo casou com um acidente (JOIN vazio)")
        for nome, (categoria, ordem) in INDICADORES.items():
            con.execute(_sql_indicador(nome, categoria, ordem))
        con.execute(SQL_INDICADOR_MENSAL)
        con.execute(SQL_INDICADOR_GERAL)
    except (duckdb.Error, ErroOuro) as erro:
        con.close()
        sys.exit(f"Ouro cancelada, nada foi alterado: {erro}")

    OURO_DIR.mkdir(parents=True, exist_ok=True)
    for nome in TABELAS_OURO:
        ordem = "id_acidente, ref_veiculo" if nome == "acidentes_veiculos" else "ALL"
        destino = _literal(OURO_DIR / f"{nome}.parquet")
        con.execute(
            f"COPY (SELECT * FROM ouro.{nome} ORDER BY {ordem}) TO '{destino}' (FORMAT parquet)"
        )
    con.close()
    print(f"ouro/acidentes_veiculos.parquet: {total} linhas")


if __name__ == "__main__":
    executar()
