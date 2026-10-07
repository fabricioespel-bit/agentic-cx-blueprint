"""Traces sem o texto da conversa (P6.2).

Os spans são capturados em memória. O classificador é um LlmAgent de verdade, com modelo
falso: é no span da chamada ao LLM que o ADK grava o pedido e a resposta, por padrão.
"""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest
from google.adk.agents.run_config import RunConfig
from google.adk.apps import App
from google.adk.models import BaseLlm, LlmResponse
from google.adk.runners import InMemoryRunner
from google.adk.telemetry.context import ContentCapturingMode, TelemetryConfig
from google.genai import types
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.auditoria.destinos import DestinoArquivo
from app.auditoria.plugin import PluginAuditoria
from app.guardrails.mascaramento import DetectorLocal, Mascarador
from app.guardrails.plugin import PluginMascaramento
from app.observabilidade.traces import (
    SEM_CONTEUDO,
    identificar_projeto,
    travar_sem_conteudo,
)
from app.orquestrador.ambiente import criar_ambiente
from app.orquestrador.fluxo import criar_classificador, criar_workflow

# O que não pode aparecer em nenhum span: dado pessoal (antes e depois do mascaramento),
# a pergunta e a resposta do modelo.
SEGREDOS = ("529.982.247-25", "[CPF]", "previsão do tempo", "fora_de_escopo")
MENSAGEM = "Meu CPF é 529.982.247-25, qual a previsão do tempo?"

_spans = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def provedor():
    # O provedor global do OpenTelemetry só pode ser definido uma vez por processo.
    atual = trace.get_tracer_provider()
    if not hasattr(atual, "add_span_processor"):
        atual = TracerProvider()
        trace.set_tracer_provider(atual)
    atual.add_span_processor(SimpleSpanProcessor(_spans))


class ModeloFalso(BaseLlm):
    async def generate_content_async(self, llm_request, stream=False):
        pedido = str(llm_request.contents)
        resposta = (
            {"intencao": "consultar_limite", "final_cartao": "1234"}
            if "limite" in pedido
            else {"intencao": "fora_de_escopo"}
        )
        yield LlmResponse(
            content=types.Content(
                role="model", parts=[types.Part(text=json.dumps(resposta))]
            ),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=10, candidates_token_count=5
            ),
        )


def nao_usado(node_input: str):
    raise AssertionError("o redator não deveria ser chamado")


@pytest.fixture
def conversa():
    ambiente = criar_ambiente()
    classificador = criar_classificador(ambiente.catalogo, ModeloFalso(model="falso"))
    agente = criar_workflow(ambiente, classificador, nao_usado, nao_usado, "teste")
    diario = DestinoArquivo(Path(tempfile.mkdtemp()) / "diario.jsonl")
    plugins = [
        PluginAuditoria(diario, ambiente.cofre, [], segundo_plano=False),
        PluginMascaramento(Mascarador([DetectorLocal()])),
    ]
    runner = InMemoryRunner(app=App(name="teste", root_agent=agente, plugins=plugins))

    def diz(texto: str, run_config: RunConfig | None = None) -> list:
        _spans.clear()

        async def _turno():
            sessao = await runner.session_service.create_session(
                app_name="teste", user_id="u"
            )
            mensagem = types.Content(role="user", parts=[types.Part(text=texto)])
            async for _ in runner.run_async(
                user_id="u",
                session_id=sessao.id,
                new_message=mensagem,
                run_config=run_config,
            ):
                pass

        asyncio.run(_turno())
        return list(_spans.get_finished_spans())

    return diz, diario


def texto_dos_spans(spans) -> str:
    partes = []
    for span in spans:
        partes += [span.name, *map(str, span.attributes.values())]
        for evento in span.events:
            partes += map(str, evento.attributes.values())
    return "\n".join(partes)


def vazados(spans) -> list[str]:
    texto = texto_dos_spans(spans)
    return [s for s in SEGREDOS if s in texto]


def test_sem_a_trava_o_adk_grava_o_texto_nos_spans(conversa, monkeypatch):
    # Controle: prova que o teste seguinte enxergaria um vazamento.
    for variavel in SEM_CONTEUDO:
        monkeypatch.delenv(variavel, raising=False)
    diz, _ = conversa
    assert vazados(diz(MENSAGEM))


def test_com_a_trava_nenhum_span_leva_o_texto(conversa):
    travar_sem_conteudo()
    diz, _ = conversa
    assert vazados(diz(MENSAGEM)) == []


def test_pedido_do_cliente_nao_liga_o_conteudo(conversa):
    travar_sem_conteudo()
    diz, _ = conversa
    pede_conteudo = RunConfig(
        telemetry=TelemetryConfig(
            capture_message_content=ContentCapturingMode.SPAN_AND_EVENT
        )
    )
    assert vazados(diz(MENSAGEM, pede_conteudo)) == []


def test_spans_proprios_levam_so_metadados(conversa):
    travar_sem_conteudo()
    diz, _ = conversa
    spans = {s.name: s for s in diz(MENSAGEM)}
    mascaramento = spans["mascaramento DetectorLocal"]
    assert mascaramento.attributes["achados"] == 1
    assert list(mascaramento.attributes["tipos"]) == ["BRAZIL_CPF_NUMBER"]
    assert spans["filtro de entrada"].attributes["barrado"] is False


def test_chamada_ao_sistema_de_cartoes_tem_span(conversa):
    travar_sem_conteudo()
    diz, _ = conversa
    nomes = {s.name for s in diz("Qual o limite do cartão final 1234?")}
    assert {n for n in nomes if n.startswith("mcp ")} >= {"mcp consultar_limite"}


def test_registro_de_auditoria_aponta_para_o_trace(conversa):
    travar_sem_conteudo()
    diz, diario = conversa
    spans = diz(MENSAGEM)
    [registro] = diario.ler()
    assert {format(s.context.trace_id, "032x") for s in spans} == {registro["trace_id"]}


def test_recurso_identifica_o_projeto(monkeypatch):
    # Sem gcp.project_id no recurso, a API de telemetria recusa o envio (400).
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "projeto-exemplo")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "ambiente=ci")
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    identificar_projeto()
    recurso = TracerProvider().resource.attributes
    assert recurso["gcp.project_id"] == "projeto-exemplo"
    assert recurso["ambiente"] == "ci"
