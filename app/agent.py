"""Agente de atendimento do Banco Exemplo: grafo do ADK ligado ao núcleo determinístico."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from google.adk.apps import App
from google.genai import types

from app.auditoria.destinos import DestinoArquivo, DestinoGoogle
from app.auditoria.plugin import PluginAuditoria
from app.conhecimento.redator import criar_redator
from app.guardrails.filtro import FiltroModelArmor
from app.guardrails.mascaramento import DetectorLocal, DetectorSDP, Mascarador
from app.guardrails.plugin import PluginMascaramento
from app.observabilidade.traces import travar_sem_conteudo
from app.orquestrador.ambiente import criar_ambiente
from app.orquestrador.fluxo import criar_classificador, criar_workflow
from app.orquestrador.modelo import GeminiComPrazo

# O .env precisa estar carregado antes de qualquer leitura de variável abaixo. Quem
# importa o pacote `app` (servidor, playground, testes) passa primeiro por aqui, antes do
# fast_api_app.py carregar o .env: sem esta linha, o agente subia sem projeto, ou seja,
# sem o SDP e sem a auditoria no Google Cloud, e sem aviso. Não sobrescreve variáveis já
# definidas (CI).
load_dotenv()
# Os spans do ADK nunca levam o texto da conversa (P6.2); vale antes da primeira chamada.
travar_sem_conteudo()
logger = logging.getLogger(__name__)

MODEL = "gemini-3.8-flash"
# Só na revisão de resposta reprovada pela verificação (decisão de multimodelo).
MODEL_REVISOR = "gemini-2.5-pro"


def _gemini(modelo: str, prazo: float) -> GeminiComPrazo:
    # Erros de servidor e de cota: repetição da biblioteca. Sem resposta no prazo:
    # repetição do GeminiComPrazo (o revisor, Pro, pensa mais e tem prazo maior).
    return GeminiComPrazo(
        model=modelo, retry_options=types.HttpRetryOptions(attempts=3), prazo=prazo
    )


projeto = os.environ.get("GOOGLE_CLOUD_PROJECT")

# Filtro de entrada do LLM (Model Armor, us-central1): só com projeto configurado.
ambiente = criar_ambiente(filtro=FiltroModelArmor(projeto) if projeto else None)

root_agent = criar_workflow(
    ambiente,
    classificador=criar_classificador(ambiente.catalogo, _gemini(MODEL, prazo=15)),
    redator=criar_redator("redator", _gemini(MODEL, prazo=20)),
    revisor=criar_redator("revisor", _gemini(MODEL_REVISOR, prazo=40)),
    # Keep in sync with agents-cli-manifest.yaml: agents-cli derives this name
    # from the project `name:` recorded there, and telemetry reports it as
    # gen_ai.agent.name. Renaming the agent only here makes the two disagree,
    # and anything selecting traces by name stops finding this agent's.
    nome="agentic_cx_blueprint",
)

# SDP regional e regras locais juntos; se o SDP falhar, as regras seguem sozinhas. Sem
# projeto configurado (testes unitários), só as regras locais.
detectores = [DetectorSDP(projeto), DetectorLocal()] if projeto else [DetectorLocal()]
mascarador = Mascarador(detectores)

# Auditoria: diário local sempre; com projeto, também o bucket com retenção travada
# (registro completo) e o BigQuery (metadados), ambos em southamerica-east1.
# AUDITORIA_NA_NUVEM=false desliga os dois: o teste de integração sobe o servidor de
# verdade, e turno de teste não pode entrar na trilha real (o bucket não deixa apagar).
diario = DestinoArquivo(
    Path(os.environ.get("AUDITORIA_DIARIO", "artifacts/auditoria/diario.jsonl"))
)
na_nuvem = (
    bool(projeto) and os.environ.get("AUDITORIA_NA_NUVEM", "true").lower() != "false"
)
destinos = (
    [
        DestinoGoogle(
            projeto,
            bucket=os.environ.get("AUDITORIA_BUCKET", f"{projeto}-auditoria"),
            tabela=os.environ.get("AUDITORIA_TABELA", f"{projeto}.auditoria.turnos"),
        )
    ]
    if na_nuvem
    else []
)

app = App(
    root_agent=root_agent,
    name="app",
    # A auditoria vem primeiro só para a duração do turno incluir o mascaramento; ela
    # não altera a mensagem, e o registro é montado no fim do turno.
    plugins=[
        PluginAuditoria(diario, ambiente.cofre, destinos, relogio=ambiente.relogio),
        PluginMascaramento(mascarador),
    ],
)

# Proteções ativas, na partida: uma proteção desligada não pode passar despercebida.
if na_nuvem:
    logger.info(
        "proteções: mascaramento com SDP regional e regras locais; filtro de entrada "
        "com Model Armor; auditoria no diário, no Cloud Storage e no BigQuery"
    )
elif projeto:
    logger.warning(
        "AUDITORIA_NA_NUVEM=false: auditoria só no diário local; mascaramento com SDP "
        "e filtro de entrada com Model Armor seguem ligados"
    )
else:
    logger.warning(
        "GOOGLE_CLOUD_PROJECT ausente: mascaramento só com regras locais (nomes e "
        "endereços passam), sem filtro de entrada e auditoria só no diário local"
    )
