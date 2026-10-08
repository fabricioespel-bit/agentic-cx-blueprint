"""Custo estimado das chamadas ao LLM, a partir do uso gravado na auditoria (P6.3).

A trilha guarda tokens, não dinheiro: o preço vem de config/custo/precos.yaml, na hora da
consulta, e cada turno usa o preço vigente na data em que aconteceu. Mudar a tabela não
exige reprocessar a trilha nem mexe na cadeia de hashes. É estimativa, não fatura.

Como o Gemini cobra: os tokens de cache fazem parte dos de entrada, mas com preço menor;
os de pensamento são cobrados como saída.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

PRECOS = Path(__file__).parents[2] / "config" / "custo" / "precos.yaml"
MILHAO = 1_000_000
CAMPOS_PRECO = ("entrada", "entrada_cache", "saida")


@dataclass(frozen=True)
class Preco:
    a_partir_de: date | None
    entrada: float
    entrada_cache: float
    saida: float


@dataclass(frozen=True)
class TabelaDePrecos:
    moeda: str
    consultado_em: date
    fonte: str
    modelos: dict[str, list[Preco]]

    def vigente(self, modelo: str, dia: date) -> Preco:
        if modelo not in self.modelos:
            raise KeyError(f"sem preço para o modelo {modelo} em precos.yaml")
        # Ordenados na carga: o primeiro sem data, os demais por data.
        validos = [
            p
            for p in self.modelos[modelo]
            if p.a_partir_de is None or p.a_partir_de <= dia
        ]
        return validos[-1]


def carregar_precos(caminho: Path = PRECOS) -> TabelaDePrecos:
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    modelos = {}
    for modelo, precos in dados["modelos"].items():
        for preco in precos:
            vazios = [c for c in CAMPOS_PRECO if preco.get(c) is None]
            if vazios:
                raise ValueError(f"{modelo}: preço vazio em {', '.join(vazios)}")
        modelos[modelo] = sorted(
            (Preco(**preco) for preco in precos),
            key=lambda p: p.a_partir_de or date.min,
        )
    return TabelaDePrecos(
        moeda=dados["moeda"],
        consultado_em=dados["consultado_em"],
        fonte=dados["fonte"],
        modelos=modelos,
    )


def custo_da_chamada(chamada: dict, dia: date, tabela: TabelaDePrecos) -> float | None:
    """Custo de uma chamada ao LLM, na moeda da tabela.

    ``None`` quando a chamada não tem contagem de tokens (terminou em erro, por exemplo):
    custo desconhecido não é custo zero.
    """
    entrada = chamada.get("tokens_entrada")
    if entrada is None:
        return None
    cache = chamada.get("tokens_cache") or 0
    saida = (chamada.get("tokens_saida") or 0) + (chamada.get("tokens_pensamento") or 0)
    preco = tabela.vigente(chamada["modelo"], dia)
    return (
        (entrada - cache) * preco.entrada
        + cache * preco.entrada_cache
        + saida * preco.saida
    ) / MILHAO
