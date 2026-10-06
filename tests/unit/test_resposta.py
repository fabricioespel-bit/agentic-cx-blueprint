"""Verificação de fundamentação e preenchimento de valores. Sem LLM."""

from decimal import Decimal

import pytest

from app.conhecimento.corpus import Valor, carregar_corpus
from app.conhecimento.resposta import (
    Afirmacao,
    Resposta,
    fontes,
    formatar,
    preencher,
    verificar,
)

CORPUS = carregar_corpus()
TRECHOS = {t.id: t for t in CORPUS.trechos}
# O que a busca "devolveu" nestes testes: só estes dois trechos.
RECUPERADOS = [
    TRECHOS["cartao-classico#anuidade"],
    TRECHOS["cartao-platinum#isencao-da-anuidade"],
]


def resposta(*afirmacoes: tuple[str, list[str]]) -> Resposta:
    return Resposta(afirmacoes=[Afirmacao(texto=t, fontes=f) for t, f in afirmacoes])


def verificar_frase(texto: str, *fontes_citadas: str) -> list[str]:
    return verificar(resposta((texto, list(fontes_citadas))), RECUPERADOS)


def test_resposta_fundamentada_aprovada_e_preenchida():
    boa = resposta(
        (
            "A anuidade do Clássico é de {{parcelas_anuidade}} parcelas de "
            "{{anuidade_classico}}.",
            ["cartao-classico#anuidade"],
        ),
        (
            "No Platinum, a parcela é isenta com gastos a partir de "
            "{{gasto_isencao_platinum}}.",
            ["cartao-platinum#isencao-da-anuidade"],
        ),
    )
    assert verificar(boa, RECUPERADOS) == []
    assert preencher(boa, CORPUS.tabela) == (
        "A anuidade do Clássico é de 12 parcelas de R$ 19,90. "
        "No Platinum, a parcela é isenta com gastos a partir de R$ 3.000,00."
    )
    assert fontes(boa) == [
        "cartao-classico#anuidade",
        "cartao-platinum#isencao-da-anuidade",
    ]


def test_sem_afirmacoes_reprovada():
    assert verificar(Resposta(afirmacoes=[]), RECUPERADOS) == ["sem afirmações"]


def test_afirmacao_sem_fonte_reprovada():
    assert verificar_frase("O cartão é ótimo.") == ["afirmação 1: sem fonte"]


def test_fonte_que_a_busca_nao_trouxe_reprovada():
    # O trecho existe no corpus, mas não veio nesta busca: o LLM não o viu.
    [problema] = verificar_frase(
        "O desbloqueio é feito só no app.", "bloqueio-e-desbloqueio#desbloqueio"
    )
    assert "fonte fora da busca" in problema


def test_valor_de_outro_trecho_reprovado():
    # Cita o trecho do Clássico, mas usa o valor do Platinum.
    [problema] = verificar_frase(
        "A anuidade do Clássico é {{anuidade_platinum}}.", "cartao-classico#anuidade"
    )
    assert "valor sem fonte citada: anuidade_platinum" in problema


@pytest.mark.parametrize(
    "texto",
    ["A anuidade é de R$ 19,90.", "São 12 parcelas de {{anuidade_classico}}."],
    ids=["valor_digitado", "numero_misturado"],
)
def test_numero_fora_de_marcador_reprovado(texto):
    [problema] = verificar_frase(texto, "cartao-classico#anuidade")
    assert "número fora de marcador" in problema


def test_marcador_malformado_reprovado():
    [problema] = verificar_frase(
        "A anuidade é {{ anuidade_classico }}.", "cartao-classico#anuidade"
    )
    assert "malformado" in problema


def test_problema_aponta_a_afirmacao():
    ruim = resposta(
        ("Texto certo com {{anuidade_classico}}.", ["cartao-classico#anuidade"]),
        ("Texto sem fonte.", []),
    )
    assert verificar(ruim, RECUPERADOS) == ["afirmação 2: sem fonte"]


@pytest.mark.parametrize(
    ("tipo", "valor", "esperado"),
    [
        ("reais", "19.90", "R$ 19,90"),
        ("reais", "1234567.5", "R$ 1.234.567,50"),
        ("percentual", "2", "2,00%"),
        ("percentual_mensal", "9.9", "9,90% ao mês"),
        ("inteiro", "12", "12"),
    ],
)
def test_formatacao_brasileira(tipo, valor, esperado):
    assert formatar(Valor(descricao="d", tipo=tipo, valor=Decimal(valor))) == esperado


def test_fonte_com_colchetes_e_normalizada():
    # O redator real já copiou o id como "[id]" (avaliação de 6/out): erro de forma.
    afirmacao = Afirmacao(
        texto="A anuidade é {{anuidade_classico}}.",
        fontes=["[cartao-classico#anuidade]", " cartao-classico#anuidade "],
    )
    assert afirmacao.fontes == ["cartao-classico#anuidade", "cartao-classico#anuidade"]
    assert verificar(Resposta(afirmacoes=[afirmacao]), RECUPERADOS) == []


def test_normalizacao_nao_aceita_outro_trecho():
    # Sem os colchetes, o id ainda precisa ser um dos recuperados.
    [problema] = verificar_frase(
        "O desbloqueio é feito só no app.", "[bloqueio-e-desbloqueio#desbloqueio]"
    )
    assert "fonte fora da busca: bloqueio-e-desbloqueio#desbloqueio" in problema
