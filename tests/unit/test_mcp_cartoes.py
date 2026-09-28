"""Servidor MCP de cartões com cliente MCP real, em memória. Sem LLM."""

import json
from dataclasses import dataclass

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as conectar

from app.mcp_cartoes.servidor import (
    META_CONFIRMACAO,
    META_SESSAO,
    ServicoCartoes,
    criar_servidor,
)
from app.mcp_cartoes.sistema import Falha, SistemaCartoes, Situacao, sistema_exemplo
from app.nucleo.catalogo import Canal, carregar_catalogo
from app.nucleo.confirmacao import Confirmacoes
from app.nucleo.execucoes import RegistroExecucoes
from app.nucleo.politica import Contexto, Politica
from app.nucleo.sessao import CofreSessao

CONTEXTO = Contexto(
    cliente_ref="cli-1", sessao_id="s1", canal=Canal.WHATSAPP, nivel_autenticacao=1
)


@dataclass
class Ambiente:
    servidor: object
    servico: ServicoCartoes
    politica: Politica
    sistema: SistemaCartoes
    token: str

    def chamar(self, ferramenta, argumentos=None, confirmacao=None, token=...):
        meta = {META_SESSAO: self.token if token is ... else token}
        if confirmacao is not None:
            meta[META_CONFIRMACAO] = confirmacao

        async def _chamar():
            async with conectar(self.servidor) as sessao:
                return await sessao.call_tool(ferramenta, argumentos or {}, meta=meta)

        resultado = anyio.run(_chamar)
        texto = resultado.content[0].text
        return (texto, True) if resultado.isError else (json.loads(texto), False)

    def confirmar(self, final="1234"):
        decisao = self.politica.avaliar(
            "bloquear_cartao_temporario", {"final_cartao": final}, CONTEXTO
        )
        return decisao.confirmacao.id

    def bloquear(self, confirmacao, final="1234"):
        return self.chamar("bloquear_cartao", {"final_cartao": final}, confirmacao)

    def situacao(self, final="1234"):
        cartoes = self.sistema.cartoes_do_cliente("cli-1")
        return next(c for c in cartoes if c.final == final).situacao


@pytest.fixture
def ambiente(relogio):
    registro = RegistroExecucoes(relogio=relogio)
    politica = Politica(
        carregar_catalogo(),
        Confirmacoes(relogio=relogio),
        contar_execucoes_hoje=registro.contar_hoje,
    )
    sistema = sistema_exemplo()
    servico = ServicoCartoes(politica, sistema, registro)
    cofre = CofreSessao()
    token = cofre.abrir(CONTEXTO)
    return Ambiente(criar_servidor(servico, cofre), servico, politica, sistema, token)


def test_schema_das_ferramentas_nao_expoe_identidade_nem_confirmacao(ambiente):
    async def _listar():
        async with conectar(ambiente.servidor) as sessao:
            return await sessao.list_tools()

    ferramentas = anyio.run(_listar).tools
    assert {f.name for f in ferramentas} == {
        "listar_cartoes",
        "consultar_limite",
        "bloquear_cartao",
    }
    for ferramenta in ferramentas:
        campos = set(ferramenta.inputSchema.get("properties", {}))
        assert campos <= {"final_cartao"}


@pytest.mark.parametrize("token", [None, "forjado"])
def test_sem_sessao_valida_recusado(ambiente, token):
    assert ambiente.chamar("listar_cartoes", token=token) == (
        "Error executing tool listar_cartoes: sessao_invalida",
        True,
    )


def test_lista_so_os_cartoes_do_cliente_da_sessao(ambiente):
    resposta, erro = ambiente.chamar("listar_cartoes")
    assert not erro
    assert [c["final"] for c in resposta["cartoes"]] == ["1234", "5678"]


def test_cartao_de_outro_cliente_nao_encontrado(ambiente):
    texto, erro = ambiente.chamar("consultar_limite", {"final_cartao": "9012"})
    assert erro and "cartao_nao_encontrado" in texto


def test_consulta_limite(ambiente):
    resposta, _ = ambiente.chamar("consultar_limite", {"final_cartao": "1234"})
    assert resposta == {
        "final": "1234",
        "limite_total": 5000,
        "limite_disponivel": 3200,
    }


def test_escrita_sem_confirmacao_recusada(ambiente):
    texto, erro = ambiente.bloquear(confirmacao=None)
    assert erro and "confirmacao_ausente" in texto
    assert ambiente.situacao() is Situacao.ATIVO


def test_bloqueio_confirmado_executa(ambiente):
    resposta, erro = ambiente.bloquear(ambiente.confirmar())
    assert not erro and resposta["estado"] == "concluida"
    assert ambiente.situacao() is Situacao.BLOQUEADO


def test_mesma_chave_executa_uma_vez(ambiente):
    confirmacao = ambiente.confirmar()
    primeira, _ = ambiente.bloquear(confirmacao)
    segunda, erro = ambiente.bloquear(confirmacao)
    assert not erro and segunda == primeira
    assert ambiente.sistema.chamadas_bloqueio == 1


def test_mesma_chave_com_outro_cartao_recusada(ambiente):
    confirmacao = ambiente.confirmar()
    ambiente.bloquear(confirmacao)
    texto, erro = ambiente.bloquear(confirmacao, final="5678")
    assert erro and "chave_em_conflito" in texto
    assert ambiente.situacao("5678") is Situacao.ATIVO


def test_timeout_depois_de_aplicar_conclui_pela_consulta_de_estado(ambiente):
    ambiente.sistema.proxima_falha = Falha.TIMEOUT_DEPOIS
    resposta, _ = ambiente.bloquear(ambiente.confirmar())
    assert resposta["estado"] == "concluida"
    assert ambiente.sistema.chamadas_bloqueio == 1


def test_timeout_antes_de_aplicar_fica_incerta_sem_afirmar_sucesso(ambiente):
    ambiente.sistema.proxima_falha = Falha.TIMEOUT_ANTES
    resposta, _ = ambiente.bloquear(ambiente.confirmar())
    assert resposta["estado"] == "incerta"
    assert resposta["protocolo"].startswith("PRT-")
    assert ambiente.situacao() is Situacao.ATIVO


def test_nova_tentativa_de_incerta_consulta_estado_e_reexecuta(ambiente):
    ambiente.sistema.proxima_falha = Falha.TIMEOUT_ANTES
    confirmacao = ambiente.confirmar()
    incerta, _ = ambiente.bloquear(confirmacao)
    resposta, _ = ambiente.bloquear(confirmacao)
    assert resposta == incerta | {"estado": "concluida"}
    assert ambiente.sistema.chamadas_bloqueio == 2
    assert ambiente.situacao() is Situacao.BLOQUEADO


def test_reconciliacao_conclui_o_que_o_sistema_aplicou_depois(ambiente):
    ambiente.sistema.proxima_falha = Falha.TIMEOUT_ANTES
    ambiente.bloquear(ambiente.confirmar())
    assert ambiente.servico.reconciliar() == []
    ambiente.sistema.bloquear("c-001")  # o sistema processou a requisição atrasada
    [resolvida] = ambiente.servico.reconciliar()
    assert resolvida["estado"] == "concluida"


def test_limite_diario_conta_execucoes_registradas(ambiente):
    for final in ("1234", "5678", "1234"):
        ambiente.bloquear(ambiente.confirmar(final), final=final)
    decisao = ambiente.politica.avaliar(
        "bloquear_cartao_temporario", {"final_cartao": "5678"}, CONTEXTO
    )
    assert decisao.motivo == "limite_diario"
