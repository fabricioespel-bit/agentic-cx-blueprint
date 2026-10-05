"""Agente de atendimento do Banco Exemplo: grafo do ADK ligado ao núcleo determinístico."""

import os

from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

from app.conhecimento.redator import criar_redator
from app.guardrails.mascaramento import DetectorLocal, DetectorSDP, Mascarador
from app.guardrails.plugin import PluginMascaramento
from app.orquestrador.ambiente import criar_ambiente
from app.orquestrador.fluxo import criar_classificador, criar_workflow

MODEL = "gemini-3.8-flash"
# Só na revisão de resposta reprovada pela verificação (decisão de multimodelo).
MODEL_REVISOR = "gemini-2.5-pro"


def _gemini(modelo: str) -> Gemini:
    return Gemini(model=modelo, retry_options=types.HttpRetryOptions(attempts=3))


ambiente = criar_ambiente()

root_agent = criar_workflow(
    ambiente,
    classificador=criar_classificador(ambiente.catalogo, _gemini(MODEL)),
    redator=criar_redator("redator", _gemini(MODEL)),
    revisor=criar_redator("revisor", _gemini(MODEL_REVISOR)),
    # Keep in sync with agents-cli-manifest.yaml: agents-cli derives this name
    # from the project `name:` recorded there, and telemetry reports it as
    # gen_ai.agent.name. Renaming the agent only here makes the two disagree,
    # and anything selecting traces by name stops finding this agent's.
    nome="agentic_cx_blueprint",
)

# SDP regional e regras locais juntos; se o SDP falhar, as regras seguem sozinhas. Sem
# projeto configurado (testes unitários), só as regras locais.
projeto = os.environ.get("GOOGLE_CLOUD_PROJECT")
detectores = [DetectorSDP(projeto), DetectorLocal()] if projeto else [DetectorLocal()]
mascarador = Mascarador(detectores)

app = App(
    root_agent=root_agent,
    name="app",
    plugins=[PluginMascaramento(mascarador)],
)
