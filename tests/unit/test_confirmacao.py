"""Confirmação amarrada aos parâmetros. Sem LLM."""

import pytest

from app.nucleo.catalogo import Intencao
from app.nucleo.confirmacao import (
    ConfirmacaoInvalida,
    Confirmacoes,
    FalhaConfirmacao,
    hash_parametros,
)

BLOQUEIO = Intencao.model_validate(
    {
        "id": "bloquear_cartao_temporario",
        "descricao": "Bloqueio temporário",
        "tipo": "transacao",
        "risco": "medio",
        "nivel_autenticacao": 1,
        "canais": ["whatsapp"],
        "fase": "autonomo",
        "exige_confirmacao": True,
        "ferramenta": "bloquear_cartao",
        "texto_confirmacao": "Bloquear o cartão final {final_cartao}?",
        "parametros": {"final_cartao": r"\d{4}"},
    }
)
PARAMS = {"final_cartao": "1234"}


@pytest.fixture
def confirmacoes(relogio):
    return Confirmacoes(relogio=relogio)


def emitir(confirmacoes):
    return confirmacoes.emitir(BLOQUEIO, "s1", PARAMS)


def consumir(
    confirmacoes, confirmacao_id, sessao="s1", intencao=BLOQUEIO.id, params=PARAMS
):
    return confirmacoes.consumir(confirmacao_id, sessao, intencao, params)


def falha(confirmacoes, confirmacao_id, **divergencia) -> FalhaConfirmacao:
    with pytest.raises(ConfirmacaoInvalida) as erro:
        consumir(confirmacoes, confirmacao_id, **divergencia)
    return erro.value.falha


def test_texto_fixo_do_catalogo_preenchido_com_parametros(confirmacoes):
    assert emitir(confirmacoes).texto == "Bloquear o cartão final 1234?"


def test_confirmacao_valida_aceita(confirmacoes):
    c = emitir(confirmacoes)
    assert consumir(confirmacoes, c.id) == c


def test_confirmacao_reutilizada_negada(confirmacoes):
    c = emitir(confirmacoes)
    consumir(confirmacoes, c.id)
    assert falha(confirmacoes, c.id) is FalhaConfirmacao.REUTILIZADA


def test_confirmacao_inexistente_negada(confirmacoes):
    assert falha(confirmacoes, "forjada") is FalhaConfirmacao.INEXISTENTE


def test_confirmacao_expirada_negada(confirmacoes, relogio):
    c = emitir(confirmacoes)
    relogio.avancar(minutes=5)
    assert falha(confirmacoes, c.id) is FalhaConfirmacao.EXPIRADA


def test_confirmacao_valida_ate_o_fim_da_validade(confirmacoes, relogio):
    c = emitir(confirmacoes)
    relogio.avancar(minutes=4, seconds=59)
    assert consumir(confirmacoes, c.id) == c


@pytest.mark.parametrize(
    "divergencia",
    [
        {"params": {"final_cartao": "9999"}},
        {"sessao": "s2"},
        {"intencao": "desbloquear_cartao"},
    ],
)
def test_qualquer_divergencia_negada(confirmacoes, divergencia):
    c = emitir(confirmacoes)
    resultado = falha(confirmacoes, c.id, **divergencia)
    assert resultado is FalhaConfirmacao.PARAMETROS_DIVERGENTES


def test_tentativa_que_falha_inutiliza_a_confirmacao(confirmacoes):
    c = emitir(confirmacoes)
    falha(confirmacoes, c.id, params={"final_cartao": "9999"})
    assert falha(confirmacoes, c.id) is FalhaConfirmacao.REUTILIZADA


def test_hash_independe_da_ordem_dos_parametros():
    assert hash_parametros("s1", "x", {"a": 1, "b": 2}) == hash_parametros(
        "s1", "x", {"b": 2, "a": 1}
    )
