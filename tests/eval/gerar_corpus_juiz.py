"""Gera tests/eval/corpus_juiz.json: cada trecho do corpus com os valores preenchidos.

O juiz roda dentro do agents-cli e não importa o pacote ``app``; lê este arquivo para
ver os trechos como o cliente os leria. Rode depois de mudar o corpus ou a tabela:

    uv run python tests/eval/gerar_corpus_juiz.py

Um teste unitário falha se o arquivo estiver desatualizado.
"""

import json
from pathlib import Path

from app.conhecimento.corpus import MARCADOR, carregar_corpus
from app.conhecimento.resposta import formatar

DESTINO = Path(__file__).parent / "corpus_juiz.json"


def trechos_preenchidos() -> dict[str, str]:
    """Chave "Título, Seção", como aparece em "Fontes consultadas"."""
    corpus = carregar_corpus()
    valores = corpus.tabela.valores
    return {
        f"{t.documento.titulo}, {t.secao}": MARCADOR.sub(
            lambda m: formatar(valores[m.group(1)]), t.texto
        )
        for t in corpus.trechos
    }


if __name__ == "__main__":
    DESTINO.write_text(
        json.dumps(trechos_preenchidos(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"{DESTINO}: {len(trechos_preenchidos())} trechos")
