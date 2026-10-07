"""Uso por turno na auditoria (P6.1): duração e chamadas ao LLM com tokens.

O classificador é um LlmAgent de verdade, com um modelo falso que devolve a resposta e o
uso de tokens: os ganchos de modelo do ADK só disparam com um LlmAgent.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest
from google.adk.apps import App
from google.adk.models import BaseLlm, LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.auditoria.destinos import DestinoArquivo
from app.auditoria.plugin import PluginAuditoria
from app.auditoria.registro import CAMPOS_LLM, VERSAO, metadados
from app.orquestrador.ambiente import criar_ambiente
from app.orquestrador.fluxo import criar_classificador, criar_workflow


class ModeloFalso(BaseLlm):
    """Classifica tudo como fora de escopo; "SEM_RESPOSTA" falha por prazo."""

    async def generate_content_async(self, llm_request, stream=False):
        if "SEM_RESPOSTA" in str(llm_request.contents):
            raise TimeoutError
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text='{"intencao": "fora_de_escopo"}')],
            ),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=812,
                candidates_token_count=14,
                thoughts_token_count=66,
            ),
        )


def nao_usado(node_input: str):
    raise AssertionError("o redator não deveria ser chamado")


@pytest.fixture
def conversa(relogio):
    ambiente = criar_ambiente(relogio=relogio)
    classificador = criar_classificador(
        ambiente.catalogo, ModeloFalso(model="modelo-falso")
    )
    agente = criar_workflow(ambiente, classificador, nao_usado, nao_usado, "teste")
    diario = DestinoArquivo(Path(tempfile.mkdtemp()) / "diario.jsonl")
    plugin = PluginAuditoria(diario, ambiente.cofre, [], relogio, segundo_plano=False)
    runner = InMemoryRunner(app=App(name="teste", root_agent=agente, plugins=[plugin]))

    def diz(texto: str) -> None:
        async def _turno():
            sessao = await runner.session_service.create_session(
                app_name="teste", user_id="u"
            )
            mensagem = types.Content(role="user", parts=[types.Part(text=texto)])
            async for _ in runner.run_async(
                user_id="u", session_id=sessao.id, new_message=mensagem
            ):
                pass

        asyncio.run(_turno())

    return diz, diario, plugin


def test_turno_registra_tokens_e_duracao_de_cada_chamada(conversa):
    diz, diario, _ = conversa
    diz("Qual a previsão do tempo?")
    [registro] = diario.ler()
    assert registro["versao"] == VERSAO
    [chamada] = registro["uso"]["llm"]
    assert chamada["no"] == "classificador"
    assert chamada["modelo"] == "modelo-falso"
    assert chamada["tokens_entrada"] == 812
    assert chamada["tokens_saida"] == 14
    assert chamada["tokens_pensamento"] == 66
    assert chamada["ms"] >= 0
    assert registro["uso"]["duracao_ms"] >= chamada["ms"]


def test_chamada_que_falha_fica_registrada_com_o_erro(conversa):
    diz, diario, plugin = conversa
    with pytest.raises(TimeoutError):
        diz("SEM_RESPOSTA")
    [registro] = diario.ler()
    assert registro["desfecho"] == "interrompido"
    [chamada] = registro["uso"]["llm"]
    assert chamada["no"] == "classificador"
    assert chamada["erro"] == "TimeoutError"
    # Nada fica pendurado no plugin depois do turno.
    assert not (plugin._inicio_turno or plugin._inicio_llm or plugin._chamadas)


def test_bigquery_recebe_as_chamadas_com_os_mesmos_campos(conversa):
    diz, diario, _ = conversa
    diz("Qual a previsão do tempo?")
    linha = metadados(diario.ler()[0], "gs://b/o.json")
    assert linha["duracao_ms"] >= 0
    [chamada] = linha["llm"]
    assert set(chamada) == set(CAMPOS_LLM)
    assert chamada["tokens_entrada"] == 812
