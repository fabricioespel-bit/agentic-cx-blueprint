"""Conversas completas pelo grafo do agente, com classificador falso. Sem LLM."""

import asyncio

import pytest
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.mcp_cartoes.sistema import Falha
from app.orquestrador.ambiente import criar_ambiente
from app.orquestrador.fluxo import criar_workflow

# O classificador falso lê a mensagem como "intencao" ou "intencao final".
# Ex.: "bloquear_cartao_temporario 1234".


def classificador(node_input: str) -> Event:
    intencao, _, final = node_input.partition(" ")
    return Event(output={"intencao": intencao, "final_cartao": final or None})


class Conversa:
    def __init__(self, relogio):
        self.ambiente = criar_ambiente(relogio=relogio)
        agente = criar_workflow(self.ambiente, classificador, nome="teste")
        self.runner = InMemoryRunner(app=App(name="teste", root_agent=agente))
        self.sessao = asyncio.run(
            self.runner.session_service.create_session(app_name="teste", user_id="u")
        )

    def diz(self, texto: str) -> str:
        async def _turno():
            respostas = []
            mensagem = types.Content(role="user", parts=[types.Part(text=texto)])
            async for evento in self.runner.run_async(
                user_id="u", session_id=self.sessao.id, new_message=mensagem
            ):
                partes = evento.content.parts if evento.content else None
                if partes and evento.author != "user":
                    respostas.extend(p.text for p in partes if p.text)
            return " ".join(respostas)

        return asyncio.run(_turno())


@pytest.fixture
def conversa(relogio):
    return Conversa(relogio)


def test_bloqueio_ponta_a_ponta(conversa):
    pergunta = conversa.diz("bloquear_cartao_temporario")
    assert "1234 (crédito) ou 5678 (débito)" in pergunta
    confirmacao = conversa.diz("o de final 1234")
    assert "Bloquear temporariamente o cartão final 1234?" in confirmacao
    assert "Responda SIM" in confirmacao
    resposta = conversa.diz("SIM")
    assert "o cartão final 1234 está bloqueado" in resposta
    assert "Protocolo PRT-" in resposta


def test_bloqueio_com_final_informado_pede_so_confirmacao(conversa):
    assert "cartão final 5678?" in conversa.diz("bloquear_cartao_temporario 5678")
    assert "está bloqueado" in conversa.diz("sim")


@pytest.mark.parametrize("resposta", ["não", "simmm", "sim, pode", "ok"])
def test_so_sim_exato_confirma(conversa, resposta):
    conversa.diz("bloquear_cartao_temporario 1234")
    assert "não fiz nenhuma alteração" in conversa.diz(resposta)
    # A pendência foi limpa: a próxima mensagem volta ao classificador.
    assert "fora do escopo" in conversa.diz("fora_de_escopo")


def test_cartao_de_outro_cliente_nao_e_aceito(conversa):
    conversa.diz("bloquear_cartao_temporario")
    assert "Não encontrei esse cartão" in conversa.diz("9012")


def test_timeout_no_sistema_nao_afirma_sucesso(conversa):
    conversa.ambiente.sistema.proxima_falha = Falha.TIMEOUT_ANTES
    conversa.diz("bloquear_cartao_temporario 1234")
    resposta = conversa.diz("SIM")
    assert "ainda não confirmou" in resposta
    assert "está bloqueado" not in resposta


def test_confirmacao_expirada_nao_executa(conversa, relogio):
    conversa.diz("bloquear_cartao_temporario 1234")
    relogio.avancar(minutes=5)
    assert "A confirmação não vale mais" in conversa.diz("SIM")


def test_desbloqueio_orienta_o_app_sem_perguntar_cartao(conversa):
    resposta = conversa.diz("desbloquear_cartao")
    assert "desbloqueio é feito só no app" in resposta
    assert "De qual cartão" not in resposta


def test_consulta_de_limite(conversa):
    resposta = conversa.diz("consultar_limite 1234")
    assert resposta == "Cartão final 1234: limite total R$ 5.000, disponível R$ 3.200."


def test_consulta_de_limite_pergunta_o_cartao(conversa):
    conversa.diz("consultar_limite")
    assert "disponível R$ 0" in conversa.diz("5678")


def test_lista_de_cartoes(conversa):
    resposta = conversa.diz("listar_cartoes")
    assert "final 1234 (crédito, ativo)" in resposta
    assert "9012" not in resposta


def test_informacao_geral_nao_improvisa(conversa):
    assert "Ainda não respondo dúvidas" in conversa.diz("duvida_produtos_tarifas")


def test_intencao_inventada_pelo_classificador_e_negada(conversa):
    assert "Não consigo fazer esse pedido" in conversa.diz("transferir_pix")
