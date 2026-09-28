"""Registro de execuções. Sem LLM."""

import pytest

from app.nucleo.execucoes import ChaveEmConflito, Estado, RegistroExecucoes

PARAMS = {"final_cartao": "1234"}
BLOQUEIO = "bloquear_cartao_temporario"


@pytest.fixture
def registro(relogio):
    return RegistroExecucoes(relogio=relogio)


def test_execucao_comeca_pendente_com_protocolo(registro):
    execucao = registro.iniciar("k1", "cli-1", BLOQUEIO, PARAMS)
    assert execucao.estado is Estado.PENDENTE
    assert execucao.protocolo.startswith("PRT-")


def test_chave_desconhecida_nao_tem_execucao(registro):
    assert registro.obter("k1", "cli-1", BLOQUEIO, PARAMS) is None


def test_mesma_chave_e_mesmos_dados_devolvem_a_execucao(registro):
    execucao = registro.iniciar("k1", "cli-1", BLOQUEIO, PARAMS)
    assert registro.obter("k1", "cli-1", BLOQUEIO, PARAMS) == execucao


@pytest.mark.parametrize(
    ("cliente", "intencao", "params"),
    [
        ("cli-2", BLOQUEIO, PARAMS),
        ("cli-1", "desbloquear_cartao", PARAMS),
        ("cli-1", BLOQUEIO, {"final_cartao": "9999"}),
    ],
)
def test_mesma_chave_com_dados_diferentes_em_conflito(
    registro, cliente, intencao, params
):
    registro.iniciar("k1", "cli-1", BLOQUEIO, PARAMS)
    with pytest.raises(ChaveEmConflito):
        registro.obter("k1", cliente, intencao, params)


def test_chave_nao_inicia_duas_vezes(registro):
    registro.iniciar("k1", "cli-1", BLOQUEIO, PARAMS)
    with pytest.raises(ChaveEmConflito):
        registro.iniciar("k1", "cli-1", BLOQUEIO, PARAMS)


def test_mudancas_de_estado(registro):
    registro.iniciar("k1", "cli-1", BLOQUEIO, PARAMS)
    assert registro.marcar_incerta("k1").estado is Estado.INCERTA
    assert [e.chave for e in registro.incertas()] == ["k1"]
    assert registro.concluir("k1").estado is Estado.CONCLUIDA
    assert registro.incertas() == []


def test_contagem_do_dia_por_cliente_e_intencao(registro, relogio):
    registro.iniciar("k1", "cli-1", BLOQUEIO, PARAMS)
    registro.iniciar("k2", "cli-1", BLOQUEIO, {"final_cartao": "5678"})
    registro.iniciar("k3", "cli-2", BLOQUEIO, PARAMS)
    assert registro.contar_hoje("cli-1", BLOQUEIO) == 2
    relogio.avancar(days=1)
    assert registro.contar_hoje("cli-1", BLOQUEIO) == 0
