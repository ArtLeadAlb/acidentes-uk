# Acidentes de trânsito no Reino Unido: bronze, prata e ouro

Pipeline em Python + DuckDB sobre o dataset
[UK Road Safety: Traffic Accidents and Vehicles](https://www.kaggle.com/datasets/tsiaras/uk-road-safety-accidents-and-vehicles)
(acidentes e veículos, 2005-2017). Os dados originais são do Department for
Transport (UK), publicados sob a
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

## Camadas

| Camada | Código | O que faz | Onde fica |
|---|---|---|---|
| Bronze | `src/bronze.py` | copia os CSVs sem alterar nada | `data/bronze/` |
| Prata | `src/prata.py` | tipagem, nulos, duplicatas, tradução da gravidade | `data/prata/*.parquet` |
| Ouro | `src/ouro.py` | JOIN dos dois arquivos pela chave `Accident_Index`, colunas derivadas e indicadores | `data/ouro/*.parquet` |

## Como rodar

```bash
uv sync
uv run python -m src.bronze        # baixa do Kaggle (precisa de credencial do Kaggle)
# ou, se os CSVs já estão numa pasta:
uv run python -m src.bronze --origem /caminho/da/pasta
uv run python -m src.prata
uv run python -m src.ouro
```

## Testes

```bash
uv run pytest --cov
```

Os testes usam dado inventado dentro de `tmp_path` e nunca abrem `data/`.
