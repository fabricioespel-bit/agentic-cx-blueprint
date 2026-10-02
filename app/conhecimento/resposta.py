"""Resposta de conhecimento: esquema, verificação de fundamentação e preenchimento.

O redator (LLM) devolve afirmações, cada uma com as fontes que a sustentam; valores só
como ``{{chave}}``. Antes de qualquer coisa chegar ao cliente, o código verifica:

- toda afirmação cita ao menos uma fonte;
- toda fonte é um trecho que a busca devolveu nesta pergunta;
- todo marcador usado aparece em um dos trechos citados pela afirmação;
- não há número fora de marcador nem marcador malformado.

Só então os marcadores viram valores da tabela oficial, formatados pelo código.

Fora do escopo (avaliação, P5): se o trecho citado de fato sustenta o sentido da
afirmação. Aqui se garante a procedência de fontes e valores, não a interpretação.
"""

import re
from decimal import Decimal

from pydantic import BaseModel, Field

from app.conhecimento.corpus import MARCADOR, TabelaValores, TipoValor, Trecho, Valor


class Afirmacao(BaseModel):
    texto: str = Field(
        description="Uma frase para o cliente. Valores só como {{chave}} do trecho."
    )
    fontes: list[str] = Field(
        description="Ids dos trechos que sustentam a frase, como aparecem na lista."
    )


class Resposta(BaseModel):
    afirmacoes: list[Afirmacao] = Field(
        description="Vazia se os trechos não respondem à pergunta."
    )


def verificar(resposta: Resposta, recuperados: list[Trecho]) -> list[str]:
    """Problemas da resposta; lista vazia quer dizer aprovada."""
    if not resposta.afirmacoes:
        return ["sem afirmações"]
    trechos = {t.id: t for t in recuperados}
    problemas = []
    for n, afirmacao in enumerate(resposta.afirmacoes, start=1):
        local = f"afirmação {n}"
        citados = [trechos[f] for f in afirmacao.fontes if f in trechos]
        if not afirmacao.fontes:
            problemas.append(f"{local}: sem fonte")
        estranhas = sorted(set(afirmacao.fontes) - trechos.keys())
        if estranhas:
            problemas.append(f"{local}: fonte fora da busca: {', '.join(estranhas)}")
        permitidos = frozenset().union(*(t.marcadores for t in citados))
        fora = sorted(set(MARCADOR.findall(afirmacao.texto)) - permitidos)
        if fora:
            problemas.append(f"{local}: valor sem fonte citada: {', '.join(fora)}")
        sem_marcadores = MARCADOR.sub("", afirmacao.texto)
        if re.search(r"\d", sem_marcadores):
            problemas.append(f"{local}: número fora de marcador")
        if "{{" in sem_marcadores or "}}" in sem_marcadores:
            problemas.append(f"{local}: marcador malformado")
    return problemas


def preencher(resposta: Resposta, tabela: TabelaValores) -> str:
    """Troca cada marcador pelo valor formatado. Só para resposta já verificada."""
    return " ".join(
        MARCADOR.sub(lambda m: formatar(tabela.valores[m.group(1)]), a.texto)
        for a in resposta.afirmacoes
    )


def fontes(resposta: Resposta) -> list[str]:
    """Ids citados, sem repetição, na ordem em que aparecem (para auditoria)."""
    return list(dict.fromkeys(f for a in resposta.afirmacoes for f in a.fontes))


def formatar(valor: Valor) -> str:
    match valor.tipo:
        case TipoValor.REAIS:
            return f"R$ {_brasileiro(valor.valor)}"
        case TipoValor.PERCENTUAL:
            return f"{_brasileiro(valor.valor)}%"
        case TipoValor.PERCENTUAL_MENSAL:
            return f"{_brasileiro(valor.valor)}% ao mês"
        case TipoValor.INTEIRO:
            return str(int(valor.valor))


def _brasileiro(numero: Decimal) -> str:
    # 3000.00 -> "3.000,00": troca os separadores do formato americano.
    return f"{numero:,.2f}".translate(str.maketrans(",.", ".,"))
