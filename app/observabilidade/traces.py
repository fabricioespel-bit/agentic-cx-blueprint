"""Traces OpenTelemetry (P6.2): só metadados, nunca o texto da conversa.

O ADK já cria um span por invocação, por nó do grafo e por chamada ao LLM, e por padrão
grava nele o pedido e a resposta do modelo. Aqui a captura de conteúdo fica travada
desligada, inclusive para um pedido que tente ligá-la pelo RunConfig: o texto da conversa
só existe na trilha de auditoria, com retenção travada e acesso restrito. O registro de
auditoria guarda o id do trace, e é por ele que os dois se ligam.

Os spans próprios (mascaramento, filtro de entrada, sistema de cartões) levam só o que é
seguro: duração, quantidade e tipo de achado, resultado. A exportação vai para o Cloud
Trace pela API de telemetria do Google; o armazenamento fica na região configurada no
projeto (padrão dos buckets de observabilidade).
"""

import logging
import os

from opentelemetry import trace

logger = logging.getLogger(__name__)

# Lidas pelo ADK a cada invocação (RunConfig.telemetry); a última trava o pedido.
SEM_CONTEUDO = {
    "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false",
    "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "NO_CONTENT",
    "ADK_TELEMETRY_IGNORE_RUN_CONFIG": "true",
}
ENDPOINT = "https://telemetry.googleapis.com/v1/traces"

tracer = trace.get_tracer("agentic_cx_blueprint")


def travar_sem_conteudo() -> None:
    """Sobrescreve, não só define: nenhuma configuração liga o conteúdo nos spans."""
    os.environ.update(SEM_CONTEUDO)


def identificar_projeto() -> None:
    """Põe o projeto nos atributos do recurso; chamar antes de o servidor criar o provedor.

    A API de telemetria recusa o envio (400) sem ``gcp.project_id`` no recurso, e o
    provedor lê ``OTEL_RESOURCE_ATTRIBUTES`` só ao ser criado.
    """
    projeto = os.environ.get("GOOGLE_CLOUD_PROJECT") or _projeto_das_credenciais()
    atributos = os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "")
    if projeto and "gcp.project_id=" not in atributos:
        os.environ["OTEL_RESOURCE_ATTRIBUTES"] = ",".join(
            filter(None, [atributos, f"gcp.project_id={projeto}"])
        )
    os.environ.setdefault("OTEL_SERVICE_NAME", "agentic-cx-blueprint")


def _projeto_das_credenciais() -> str | None:
    import google.auth

    return google.auth.default()[1]


def exportar_para_o_google() -> bool:
    """Acrescenta o envio ao Cloud Trace ao provedor que o servidor do ADK criou.

    Só traces: o ``otel_to_cloud`` do ADK liga também métricas e logs, e os logs do
    ADK podem levar o conteúdo das mensagens.
    """
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provedor = trace.get_tracer_provider()
    if not hasattr(provedor, "add_span_processor"):
        logger.warning("traces: sem provedor do OpenTelemetry; nada é exportado")
        return False
    if "gcp.project_id" not in provedor.resource.attributes:
        logger.warning("traces: recurso sem gcp.project_id; nada é exportado")
        return False
    credenciais, _ = google.auth.default()
    exportador = OTLPSpanExporter(
        session=AuthorizedSession(credenciais), endpoint=ENDPOINT
    )
    provedor.add_span_processor(BatchSpanProcessor(exportador))
    return True


def trace_atual() -> str | None:
    contexto = trace.get_current_span().get_span_context()
    return format(contexto.trace_id, "032x") if contexto.is_valid else None
