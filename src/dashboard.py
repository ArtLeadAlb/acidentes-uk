"""Dashboard de acidentes de trânsito no Reino Unido (Streamlit).

Regra do projeto: o dashboard lê SOMENTE as tabelas de indicadores da camada
ouro (data/ouro/indicador_*.parquet) e não calcula nada na tela. Aqui só
existem leitura, filtro, ordenação e formatação de números e datas. Toda soma,
contagem e percentual vem pronta do src/ouro.py.

Para rodar (na raiz do projeto, depois de rodar bronze, prata e ouro):
    uv run streamlit run dashboard.py
"""

import altair as alt
import duckdb
import streamlit as st

from config import OURO_DIR

st.set_page_config(
    page_title="Acidentes de trânsito no Reino Unido",
    page_icon="🚦",
    layout="wide",
)

TABELAS = (
    "indicador_geral",
    "indicador_mensal",
    "indicador_periodo_dia",
    "indicador_tipo_veiculo",
    "indicador_idade_veiculo",
)


@st.cache_data
def _ler(nome: str, versao: float):
    """Lê um Parquet da ouro. 'versao' (data de modificação) renova o cache
    quando a ouro é regerada."""
    arquivo = (OURO_DIR / f"{nome}.parquet").as_posix()
    return duckdb.sql(f"SELECT * FROM read_parquet('{arquivo}')").df()


def carregar(nome: str):
    return _ler(nome, (OURO_DIR / f"{nome}.parquet").stat().st_mtime)


def inteiro(valor) -> str:
    return f"{int(valor):,}".replace(",", ".")


def percentual(valor) -> str:
    return f"{float(valor):.2f}".replace(".", ",") + "%"


def barras_verticais(df, categoria: str, metrica: str, rotulo: str, tooltip: list):
    """Barras na ordem em que o DataFrame já chegou (ordenado antes)."""
    return (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X(f"{categoria}:N", sort=list(df[categoria]), title=None),
            y=alt.Y(f"{metrica}:Q", title=rotulo),
            tooltip=tooltip,
        )
        .properties(height=320)
    )


def barras_horizontais(df, categoria: str, metrica: str, rotulo: str, tooltip: list):
    return (
        alt.Chart(df)
        .mark_bar()
        .encode(
            y=alt.Y(f"{categoria}:N", sort=list(df[categoria]), title=None),
            x=alt.X(f"{metrica}:Q", title=rotulo),
            tooltip=tooltip,
        )
        .properties(height=max(320, 28 * len(df)))
    )


T_ACIDENTES = alt.Tooltip("acidentes:Q", title="Acidentes", format=",")
T_FATAIS = alt.Tooltip("acidentes_fatais:Q", title="Acidentes fatais", format=",")
T_PCT = alt.Tooltip("pct_fatais:Q", title="% fatais", format=".2f")
T_VEICULOS = alt.Tooltip("veiculos:Q", title="Veículos", format=",")

# ---------------------------------------------------------------- verificação

faltando = [n for n in TABELAS if not (OURO_DIR / f"{n}.parquet").is_file()]
if faltando:
    st.title("Acidentes de trânsito no Reino Unido")
    st.error(
        "Não encontrei os indicadores da ouro: " + ", ".join(faltando) + ". "
        "Rode `uv run python -m src.bronze`, `uv run python -m src.prata` e "
        "`uv run python -m src.ouro` e atualize a página."
    )
    st.stop()

geral = carregar("indicador_geral").iloc[0]
mensal = carregar("indicador_mensal").sort_values("mes_referencia")
periodo = carregar("indicador_periodo_dia").sort_values("ordem")
tipo = carregar("indicador_tipo_veiculo").sort_values("acidentes", ascending=False)
idade = carregar("indicador_idade_veiculo").sort_values("ordem")

# ---------------------------------------------------------------- cabeçalho

st.title("🚦 Acidentes de trânsito no Reino Unido")
st.caption(
    f"Acidentes com vítimas registrados de {geral['data_inicio']:%d/%m/%Y} "
    f"a {geral['data_fim']:%d/%m/%Y}, cruzados com os veículos envolvidos."
)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Acidentes", inteiro(geral["acidentes"]))
c2.metric("Veículos envolvidos", inteiro(geral["veiculos"]))
c3.metric("Vítimas", inteiro(geral["vitimas"]))
c4.metric("Acidentes fatais", inteiro(geral["acidentes_fatais"]))
c5.metric("% de acidentes fatais", percentual(geral["pct_fatais"]))

st.divider()

# ---------------------------------------------------------------- evolução

st.subheader("Evolução mensal")
METRICAS_MENSAIS = {
    "Acidentes": "acidentes",
    "Acidentes fatais": "acidentes_fatais",
    "Vítimas": "vitimas",
}
escolha = st.selectbox("Indicador", list(METRICAS_MENSAIS))
coluna = METRICAS_MENSAIS[escolha]
st.altair_chart(
    alt.Chart(mensal)
    .mark_line(point=True)
    .encode(
        x=alt.X("mes_referencia:T", title="Mês"),
        y=alt.Y(f"{coluna}:Q", title=escolha),
        tooltip=[
            alt.Tooltip("mes_referencia:T", title="Mês", format="%m/%Y"),
            alt.Tooltip(f"{coluna}:Q", title=escolha, format=","),
        ],
    )
    .properties(height=340),
)

st.divider()

# ---------------------------------------------------------------- período do dia

st.subheader("Quando acontecem")
esq, dir_ = st.columns(2)
esq.markdown("**Acidentes por período do dia**")
esq.altair_chart(
    barras_verticais(periodo, "periodo_dia", "acidentes", "Acidentes", ["periodo_dia", T_ACIDENTES, T_VEICULOS]),
)
dir_.markdown("**% de acidentes fatais por período do dia**")
dir_.altair_chart(
    barras_verticais(periodo, "periodo_dia", "pct_fatais", "% fatais", ["periodo_dia", T_PCT, T_FATAIS]),
)

st.divider()

# ---------------------------------------------------------------- tipo de veículo

st.subheader("Tipos de veículo")
col_a, col_b = st.columns([1, 2])
metrica_tipo = col_a.radio(
    "Mostrar",
    ["Acidentes", "% de acidentes fatais"],
    help="O percentual de fatais fica instável com poucos acidentes; use o mínimo abaixo.",
)
minimo = col_a.number_input("Mínimo de acidentes do tipo", min_value=1, value=100, step=50)

filtrado = tipo[tipo["acidentes"] >= minimo]
if filtrado.empty:
    col_b.info("Nenhum tipo de veículo atinge esse mínimo de acidentes.")
elif metrica_tipo == "Acidentes":
    col_b.altair_chart(
        barras_horizontais(filtrado, "tipo_veiculo", "acidentes", "Acidentes", ["tipo_veiculo", T_ACIDENTES, T_VEICULOS]),
        )
else:
    por_pct = filtrado.sort_values("pct_fatais", ascending=False)
    col_b.altair_chart(
        barras_horizontais(por_pct, "tipo_veiculo", "pct_fatais", "% de acidentes fatais", ["tipo_veiculo", T_PCT, T_ACIDENTES]),
        )

st.divider()

# ---------------------------------------------------------------- idade do veículo

st.subheader("Idade do veículo")
esq, dir_ = st.columns(2)
esq.markdown("**Veículos envolvidos por faixa de idade**")
esq.altair_chart(
    barras_verticais(idade, "faixa_idade_veiculo", "veiculos", "Veículos", ["faixa_idade_veiculo", T_VEICULOS, T_ACIDENTES]),
)
dir_.markdown("**% de acidentes fatais por faixa de idade**")
dir_.altair_chart(
    barras_verticais(idade, "faixa_idade_veiculo", "pct_fatais", "% fatais", ["faixa_idade_veiculo", T_PCT, T_FATAIS]),
)

# ---------------------------------------------------------------- dados e fonte

with st.expander("Ver as tabelas de indicadores"):
    st.markdown("**Por mês**")
    st.dataframe(mensal, hide_index=True)
    st.markdown("**Por período do dia**")
    st.dataframe(periodo, hide_index=True)
    st.markdown("**Por tipo de veículo**")
    st.dataframe(tipo, hide_index=True)
    st.markdown("**Por idade do veículo**")
    st.dataframe(idade, hide_index=True)

st.caption(
    "Fonte: Department for Transport (Reino Unido), Road Safety Data, publicado sob a "
    "Open Government Licence v3.0 e disponibilizado no Kaggle por tsiaras. "
    "Só acidentes que casam com ao menos um veículo entram nos indicadores."
)
