"""Busca lexical local sobre o corpus do repositório. Sem LLM."""

from datetime import date

import pytest

from app.conhecimento.busca import BuscadorLocal, termos
from app.conhecimento.corpus import carregar_corpus

DIA = date(2026, 10, 1)


@pytest.fixture(scope="module")
def buscador():
    return BuscadorLocal(carregar_corpus())


def ids(buscador, pergunta, dia=DIA):
    return [t.id for t in buscador.buscar(pergunta, dia)]


def test_termos_normaliza_e_ignora_marcadores():
    assert termos("As Tarifas do Cartão {{saque_credito}}") == {"tarifa", "cartao"}


def test_pergunta_direta_traz_a_secao_certa_primeiro(buscador):
    assert ids(buscador, "Qual a anuidade do cartão Clássico?")[0] == (
        "cartao-classico#anuidade"
    )


def test_titulo_da_secao_desempata_trechos_do_mesmo_documento(buscador):
    assert ids(buscador, "como desbloqueio meu cartão?")[0] == (
        "bloqueio-e-desbloqueio#desbloqueio"
    )


def test_excecao_chega_junto_com_a_regra(buscador):
    [trecho] = buscador.buscar("quanto custa a segunda via?", DIA)
    assert trecho.id == "tarifas-servicos#segunda-via-do-cartao"
    assert "perda, roubo ou furto" in trecho.texto


def test_corte_relativo_descarta_trecho_fraco(buscador):
    # "Benefícios" do Clássico fala em "sem juros": casa o termo, mas fica abaixo do corte.
    assert ids(buscador, "qual o juros do rotativo?") == [
        "fatura-e-pagamento#pagamento-minimo-e-credito-rotativo",
        "fatura-e-pagamento#atraso-no-pagamento",
    ]


@pytest.mark.parametrize(
    "pergunta",
    [
        "qual a previsão do tempo?",
        "cartão",
        "quanto pago por ano para ter o cartão?",
        "perdi meu cartão",
    ],
    ids=["fora_do_corpus", "vaga", "sinonimo", "variacao_de_verbo"],
)
def test_sem_fonte_devolve_vazio(buscador, pergunta):
    assert buscador.buscar(pergunta, DIA) == []


def test_so_busca_documentos_vigentes(buscador):
    assert ids(buscador, "Qual a anuidade do cartão Clássico?", date(2026, 8, 31)) == []
