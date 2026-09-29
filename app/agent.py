"""Agente de atendimento do Banco Exemplo: grafo do ADK ligado ao núcleo determinístico."""

from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

from app.orquestrador.ambiente import criar_ambiente
from app.orquestrador.fluxo import criar_classificador, criar_workflow

MODEL = "gemini-3.8-flash"

ambiente = criar_ambiente()

root_agent = criar_workflow(
    ambiente,
    classificador=criar_classificador(
        ambiente.catalogo,
        Gemini(model=MODEL, retry_options=types.HttpRetryOptions(attempts=3)),
    ),
    # Keep in sync with agents-cli-manifest.yaml: agents-cli derives this name
    # from the project `name:` recorded there, and telemetry reports it as
    # gen_ai.agent.name. Renaming the agent only here makes the two disagree,
    # and anything selecting traces by name stops finding this agent's.
    nome="agentic_cx_blueprint",
)

app = App(
    root_agent=root_agent,
    name="app",
)
