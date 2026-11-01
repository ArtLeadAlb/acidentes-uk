"""Camada bronze: traz os CSVs do Kaggle para data/bronze sem alterar nada.

SPEC
1. Origem: a pasta passada em --origem ou, sem ela, o download do dataset
   tsiaras/uk-road-safety-accidents-and-vehicles via kagglehub.
2. Destino: data/bronze. Os dois arquivos são copiados byte a byte.
3. Nenhuma limpeza, renomeação ou conversão acontece aqui.

CRITÉRIOS DE ACEITE
- Os arquivos em data/bronze são idênticos, byte a byte, aos da origem.
- Os arquivos da origem não são modificados.
- Se faltar qualquer um dos dois arquivos na origem, encerra com SystemExit
  e data/bronze não é criada.
- Sem --origem, o download é feito pelo kagglehub e a pasta devolvida por ele
  é usada como origem.
- Rodar duas vezes seguidas deixa o mesmo resultado.
"""

import argparse
import shutil
import sys
from pathlib import Path

from src.config import (
    ARQUIVO_ACIDENTES,
    ARQUIVO_VEICULOS,
    BRONZE_DIR,
    DATASET_KAGGLE,
)

ARQUIVOS = (ARQUIVO_ACIDENTES, ARQUIVO_VEICULOS)


def baixar_dataset() -> Path:
    """Baixa o dataset do Kaggle (cache do kagglehub) e devolve a pasta."""
    import kagglehub

    return Path(kagglehub.dataset_download(DATASET_KAGGLE))


def copiar_arquivos(origem: Path, destino: Path) -> None:
    faltando = [nome for nome in ARQUIVOS if not (origem / nome).is_file()]
    if faltando:
        sys.exit(f"Arquivo(s) faltando em {origem}: {', '.join(faltando)}")
    destino.mkdir(parents=True, exist_ok=True)
    for nome in ARQUIVOS:
        shutil.copyfile(origem / nome, destino / nome)
        print(f"bronze: {destino / nome}")


def executar(origem: Path | None = None) -> None:
    if origem is None:
        origem = baixar_dataset()
    copiar_arquivos(origem, BRONZE_DIR)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Camada bronze")
    parser.add_argument(
        "--origem",
        type=Path,
        help="pasta que já contém os CSVs (sem isto, baixa do Kaggle)",
    )
    executar(parser.parse_args(argv).origem)


if __name__ == "__main__":
    main()
