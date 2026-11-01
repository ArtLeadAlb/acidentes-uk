"""Caminhos e nomes compartilhados pelas camadas.

Os caminhos são relativos à pasta de onde o comando é executado (a raiz do
projeto). Os testes usam monkeypatch.chdir(tmp_path) para redirecioná-los.
"""

from pathlib import Path

DATASET_KAGGLE = "tsiaras/uk-road-safety-accidents-and-vehicles"
ARQUIVO_ACIDENTES = "Accident_Information.csv"
ARQUIVO_VEICULOS = "Vehicle_Information.csv"

BRONZE_DIR = Path("data/bronze")
PRATA_DIR = Path("data/prata")
OURO_DIR = Path("data/ouro")
