"""Plugin do ADK que grava um registro de auditoria no fim de cada turno (P4.2).

Lê os eventos do turno e o resumo que o grafo deixou no estado (``turno``), monta o
registro, encadeia o hash com o anterior da sessão (guardado no estado, em
``auditoria``), grava primeiro no diário local e envia aos destinos em segundo plano.
Falha no envio não derruba a conversa: fica registrada, e o registro segue no diário.

Também mede o turno (P6.1): duração desde a chegada da mensagem e, por chamada ao LLM, o
nó, o modelo, os tokens e a duração. Só números; o custo é calculado na consulta, com a
tabela de preços vigente.
"""

import asyncio
import logging
import time
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.models import LlmRequest, LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

from app.auditoria.destinos import Destino, DestinoArquivo
from app.auditoria.registro import GENESE, NOS_COM_LLM, montar_registro
from app.nucleo.confirmacao import Relogio, agora_utc
from app.nucleo.sessao import CofreSessao
from app.orquestrador.atendimento import HISTORICO_MAX

logger = logging.getLogger(__name__)


def _texto(evento: Event) -> str:
    partes = evento.content.parts if evento.content else None
    return "".join(p.text or "" for p in partes or [])


class PluginAuditoria(BasePlugin):
    def __init__(
        self,
        diario: DestinoArquivo,
        cofre: CofreSessao,
        destinos: list[Destino] | None = None,
        relogio: Relogio = agora_utc,
        segundo_plano: bool = True,
    ):
        super().__init__(name="auditoria")
        self._diario = diario
        self._cofre = cofre
        # "is None", não "or": uma lista vazia recebida precisa ser a mesma lista.
        self._destinos = destinos if destinos is not None else []
        self._relogio = relogio
        self._segundo_plano = segundo_plano
        self._envios: set[asyncio.Task] = set()
        # Medições do turno em andamento, por invocação (o plugin atende turnos em
        # paralelo): início do turno, início da chamada ao LLM por nó, chamadas feitas.
        self._inicio_turno: dict[str, float] = {}
        self._inicio_llm: dict[tuple[str, str], tuple[float, str]] = {}
        self._chamadas: dict[str, list[dict[str, Any]]] = {}

    async def on_user_message_callback(
        self, *, invocation_context: InvocationContext, user_message: types.Content
    ) -> None:
        self._inicio_turno[invocation_context.invocation_id] = time.monotonic()

    async def before_model_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> None:
        chave = (callback_context.invocation_id, callback_context.agent_name)
        self._inicio_llm[chave] = (time.monotonic(), llm_request.model or "")

    async def after_model_callback(
        self, *, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> None:
        uso = llm_response.usage_metadata
        self._chamada(
            callback_context,
            tokens_entrada=uso.prompt_token_count if uso else None,
            tokens_saida=uso.candidates_token_count if uso else None,
            tokens_pensamento=uso.thoughts_token_count if uso else None,
            tokens_cache=uso.cached_content_token_count if uso else None,
        )

    async def on_model_error_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
        error: Exception,
    ) -> None:
        self._chamada(callback_context, erro=type(error).__name__)

    def _chamada(self, contexto: CallbackContext, **campos: Any) -> None:
        chave = (contexto.invocation_id, contexto.agent_name)
        inicio, modelo = self._inicio_llm.pop(chave, (None, ""))
        self._chamadas.setdefault(contexto.invocation_id, []).append(
            {
                "no": contexto.agent_name,
                "modelo": modelo,
                "ms": _ms(inicio),
                **campos,
            }
        )

    async def after_run_callback(
        self, *, invocation_context: InvocationContext
    ) -> None:
        await self._registrar(invocation_context)

    async def on_run_error_callback(
        self, *, invocation_context: InvocationContext, error: Exception
    ) -> None:
        # Turno que terminou em erro (ex.: prazo do LLM estourado nas duas tentativas)
        # também entra na trilha, com desfecho "interrompido" e o tipo do erro no
        # motivo. O gancho só notifica: o erro segue para o runner de qualquer forma.
        try:
            await self._registrar(
                invocation_context, motivo=f"erro:{type(error).__name__}"
            )
        except Exception:
            logger.exception("auditoria: turno com erro não foi registrado")

    async def _registrar(
        self, ic: InvocationContext, motivo: str | None = None
    ) -> None:
        sessao = ic.session
        uso = {
            "duracao_ms": _ms(self._inicio_turno.pop(ic.invocation_id, None)),
            "llm": self._chamadas.pop(ic.invocation_id, []),
        }
        eventos = [e for e in sessao.events if e.invocation_id == ic.invocation_id]
        com_texto = [e for e in eventos if _texto(e)]
        mensagem = next((_texto(e) for e in com_texto if e.author == "user"), "")
        respostas = [
            _texto(e)
            for e in com_texto
            if e.author != "user" and e.author not in NOS_COM_LLM
        ]
        mexeu_no_conhecimento = any(
            "conhecimento" in (e.actions.state_delta or {}) for e in eventos
        )
        anterior = sessao.state.get("auditoria") or {"sequencia": 0, "hash": GENESE}
        turno = sessao.state.get("turno") or {}
        if motivo:
            turno = {**turno, "motivo": motivo}
        registro = montar_registro(
            sessao=sessao.id,
            sequencia=anterior["sequencia"] + 1,
            momento=self._relogio(),
            cliente_ref=self._cliente(sessao.state.get("sessao")),
            mensagem=mensagem,
            resposta=respostas[-1] if respostas else "",
            turno=turno,
            conhecimento=(
                sessao.state.get("conhecimento") if mexeu_no_conhecimento else None
            ),
            chamadas_llm=[e.author for e in com_texto if e.author in NOS_COM_LLM],
            uso=uso,
            hash_anterior=anterior["hash"],
        )
        # O elo da próxima vez fica no estado da sessão, persistido com ela, e um item
        # curto vai para o histórico, de onde sai o resumo do escalonamento (P4.3).
        elo = {"sequencia": registro["sequencia"], "hash": registro["hash"]}
        item = {k: registro[k] for k in ("intencao", "desfecho", "motivo")}
        historico = (sessao.state.get("historico") or [])[-(HISTORICO_MAX - 1) :]
        await ic.session_service.append_event(
            sessao,
            Event(
                author="auditoria",
                invocation_id=ic.invocation_id,
                actions=EventActions(
                    state_delta={"auditoria": elo, "historico": [*historico, item]}
                ),
            ),
        )
        await asyncio.to_thread(self._diario.gravar, registro)
        envio = self._enviar(registro)
        if self._segundo_plano:
            tarefa = asyncio.create_task(envio)
            self._envios.add(tarefa)  # referência viva até terminar
            tarefa.add_done_callback(self._envios.discard)
        else:
            await envio

    async def _enviar(self, registro: dict[str, Any]) -> None:
        for destino in self._destinos:
            try:
                await asyncio.to_thread(destino.gravar, registro)
            except Exception:
                logger.warning(
                    "auditoria: envio a %s falhou (sessão %s, sequência %s)",
                    type(destino).__name__,
                    registro["sessao"],
                    registro["sequencia"],
                )

    def _cliente(self, token: str | None) -> str | None:
        try:
            return self._cofre.resolver(token).cliente_ref
        except Exception:
            return None


def _ms(inicio: float | None) -> int | None:
    return None if inicio is None else round((time.monotonic() - inicio) * 1000)
