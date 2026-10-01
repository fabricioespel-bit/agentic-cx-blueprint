"""Conversas completas pelo grafo do agente, com classificador falso. Sem LLM."""

import asyncio
from datetime import UTC, datetime

import pytest
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.mcp_cartoes.sistema import Falha
from app.orquestrador.ambiente import criar_ambiente
from app.orquestrador.fluxo import criar_workflow

# O classificador falso lê a mensagem como "intencao" ou "intencao final".
# Ex.: "bloquear_cartao_temporario 1234". Mensagem terminada em "?" é dúvida.


def classificador(node_input: str) -> Event:
    if node_input.endswith("?"):
        return Event(output={"intencao": "duvida_produtos_tarifas"})
    intencao, _, final = node_input.partition(" ")
    return Event(output={"intencao": intencao, "final_cartao": final or None})


class Conversa:
    def __init__(self, relogio):
        self.ambiente = criar_ambiente(relogio=relogio)
        # Redatores falsos: devolvem a resposta definida pelo teste e guardam o pedido
        # que receberam, para o teste conferir o que o LLM teria visto.
        self.redacoes: dict[str, dict] = {}
        self.pedidos: dict[str, str] = {}

        def redator(node_input: str) -> Event:
            return self._redigir("redator", node_input)

        def revisor(node_input: str) -> Event:
            return self._redigir("revisor", node_input)

        agente = criar_workflow(
            self.ambiente, classificador, redator, revisor, nome="teste"
        )
        self.runner = InMemoryRunner(app=App(name="teste", root_agent=agente))
        self.sessao = asyncio.run(
            self.runner.session_service.create_session(app_name="teste", user_id="u")
        )

    def _redigir(self, papel: str, pedido: str) -> Event:
        self.pedidos[papel] = pedido
        return Event(output=self.redacoes[papel])

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


@pytest.mark.parametrize(
    "mensagens",
    [["bloquear_cartao_temporario 1234"], ["bloquear_cartao_temporario", "1234"]],
    ids=["final_na_mensagem", "escolha_do_cartao"],
)
def test_cartao_ja_bloqueado_nao_pede_confirmacao(conversa, mensagens):
    conversa.ambiente.sistema.bloquear("c-001")  # bloqueado pelo app
    *_, resposta = [conversa.diz(m) for m in mensagens]
    assert "O cartão final 1234 já está bloqueado" in resposta
    assert "Responda SIM" not in resposta
    assert conversa.ambiente.sistema.chamadas_bloqueio == 1
    # Sem pendência: a próxima mensagem volta ao classificador.
    assert "fora do escopo" in conversa.diz("fora_de_escopo")


def test_cartao_bloqueado_antes_do_sim_nao_responde_falha(conversa):
    conversa.diz("bloquear_cartao_temporario 1234")
    conversa.ambiente.sistema.bloquear("c-001")  # bloqueado pelo app nesse meio-tempo
    resposta = conversa.diz("SIM")
    assert "já está bloqueado" in resposta
    assert "Não consegui concluir" not in resposta
    assert conversa.ambiente.sistema.chamadas_bloqueio == 1


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


def test_intencao_inventada_pelo_classificador_e_negada(conversa):
    assert "Não consigo fazer esse pedido" in conversa.diz("transferir_pix")


# Conhecimento. O corpus vale a partir de 1º/set/2026; o relógio dos testes começa antes.
ANUIDADE = "cartao-classico#anuidade"
PERGUNTA = "Qual a anuidade do cartão Clássico?"


def afirmacao(texto: str, *fontes: str) -> dict:
    return {"afirmacoes": [{"texto": texto, "fontes": list(fontes)}]}


BOA = afirmacao(
    "A anuidade do Clássico é de {{parcelas_anuidade}} parcelas de "
    "{{anuidade_classico}}.",
    ANUIDADE,
)


@pytest.fixture
def vigente(conversa, relogio):
    relogio.agora = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    return conversa


def test_duvida_respondida_com_valor_da_tabela_e_fonte(vigente):
    vigente.redacoes["redator"] = BOA
    assert vigente.diz(PERGUNTA) == (
        "A anuidade do Clássico é de 12 parcelas de R$ 19,90.\n\n"
        "Fontes consultadas: Cartão Exemplo Clássico, Anuidade."
    )
    # O LLM vê o marcador, nunca o valor; e o revisor não foi chamado.
    assert "{{anuidade_classico}}" in vigente.pedidos["redator"]
    assert "19,90" not in vigente.pedidos["redator"]
    assert "revisor" not in vigente.pedidos


def test_reprovada_vai_ao_revisor_com_os_problemas(vigente):
    vigente.redacoes["redator"] = afirmacao(
        "A anuidade do Clássico é {{anuidade_platinum}}.", ANUIDADE
    )
    vigente.redacoes["revisor"] = BOA
    assert "R$ 19,90" in vigente.diz(PERGUNTA)
    assert "valor sem fonte citada: anuidade_platinum" in vigente.pedidos["revisor"]


def test_reprovada_duas_vezes_recusa_sem_texto_do_llm(vigente):
    vigente.redacoes["redator"] = afirmacao("A anuidade é R$ 9,90.", ANUIDADE)
    vigente.redacoes["revisor"] = afirmacao("A anuidade é R$ 9,90.", ANUIDADE)
    resposta = vigente.diz(PERGUNTA)
    assert "Não encontrei essa informação" in resposta
    assert "9,90" not in resposta


def test_redator_sem_resposta_recusa_sem_chamar_o_revisor(vigente):
    # Achado do playground (1º/out): a busca traz um trecho só vizinho do tema e o
    # redator recusa; antes, o revisor era acionado e respondia fora do tema.
    vigente.redacoes["redator"] = {"afirmacoes": []}
    assert "Não encontrei essa informação" in vigente.diz(
        "O cartão Platinum dá cashback?"
    )
    assert "redator" in vigente.pedidos
    assert "revisor" not in vigente.pedidos


def test_sem_trecho_nao_chama_o_llm(vigente):
    assert "Não encontrei essa informação" in vigente.diz("Vai chover amanhã?")
    assert vigente.pedidos == {}


def test_documento_ainda_nao_vigente_nao_e_usado(conversa):
    # Relógio em 1º/jan/2026: nenhum documento do corpus vale ainda.
    assert "Não encontrei essa informação" in conversa.diz(PERGUNTA)
    assert conversa.pedidos == {}
