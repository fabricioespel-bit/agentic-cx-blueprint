"""Busca no corpus: a interface e uma implementação lexical local.

``Buscador`` é a porta: o agente só conhece ``buscar``. ``BuscadorLocal`` pontua os
trechos vigentes pelos termos em comum com a pergunta, com peso pela raridade do termo
no corpus (IDF) e peso dobrado para o título da seção. Dois cortes decidem o que volta:
pontuação mínima e uma fração da pontuação do melhor trecho. Sem trecho acima dos
cortes, devolve lista vazia: o agente diz que não encontrou fonte, em vez de redigir
sobre texto irrelevante.

Mock: busca lexical, sem sinônimos nem variações de verbo ("perdi" não encontra
"perda"); a busca semântica vem pelo adaptador do RAG Engine (P3.6), atrás da mesma
interface. Cortes calibrados no corpus fictício; em produção, na avaliação (P5).
"""

import math
import re
import unicodedata
from collections import Counter
from datetime import date
from typing import Protocol

from app.conhecimento.corpus import MARCADOR, Corpus, Trecho

PALAVRAS_VAZIAS = frozenset(
    """a o as os um uma de da do das dos e em no na nos nas ao aos por pelo pela para
com sem que qual quais quanto quanta quantos como onde quando meu minha meus minhas
seu sua eu voce se me ou mais tem ter sobre isso esse essa este esta ja nao sim""".split()
)
PESO_SECAO = 2.0


class Buscador(Protocol):
    def buscar(self, pergunta: str, dia: date) -> list[Trecho]: ...


def termos(texto: str) -> frozenset[str]:
    """Sem marcadores e acentos, minúsculas, sem palavras vazias, no singular."""
    sem_marcadores = MARCADOR.sub(" ", texto)
    ascii_ = unicodedata.normalize("NFKD", sem_marcadores).encode("ascii", "ignore")
    palavras = re.findall(r"[a-z]+", ascii_.decode().lower())
    return frozenset(
        _singular(p) for p in palavras if p not in PALAVRAS_VAZIAS and len(p) > 1
    )


def _singular(palavra: str) -> str:
    """Só o plural simples ("tarifas" -> "tarifa"). Cortar prefixos traz falso positivo: "tempo" casaria com "temporário"."""
    return palavra[:-1] if len(palavra) > 3 and palavra.endswith("s") else palavra


class BuscadorLocal:
    def __init__(
        self,
        corpus: Corpus,
        limite: int = 3,
        minimo: float = 1.5,
        fracao_do_melhor: float = 0.5,
    ):
        self._corpus = corpus
        self._limite = limite
        self._minimo = minimo
        self._fracao = fracao_do_melhor
        # Por trecho: termos do texto (com o título do documento) e do título da seção.
        self._termos = {
            t.id: (termos(f"{t.documento.titulo} {t.texto}"), termos(t.secao))
            for t in corpus.trechos
        }
        frequencia = Counter(
            termo for texto, secao in self._termos.values() for termo in texto | secao
        )
        total = len(self._termos)
        self._idf = {termo: math.log(total / n) for termo, n in frequencia.items()}

    def buscar(self, pergunta: str, dia: date) -> list[Trecho]:
        consulta = termos(pergunta)
        pontuados = sorted(
            ((self._pontos(consulta, t), t) for t in self._corpus.vigentes(dia)),
            key=lambda par: (-par[0], par[1].id),
        )
        if not pontuados or pontuados[0][0] < self._minimo:
            return []
        corte = max(self._minimo, self._fracao * pontuados[0][0])
        return [t for pontos, t in pontuados[: self._limite] if pontos >= corte]

    def _pontos(self, consulta: frozenset[str], trecho: Trecho) -> float:
        texto, secao = self._termos[trecho.id]
        return sum(
            self._idf[termo] * (PESO_SECAO if termo in secao else 1.0)
            for termo in consulta
            if termo in texto or termo in secao
        )
