"""Plugin do ADK que grava um registro de auditoria no fim de cada turno (P4.2).

Lê os eventos do turno e o resumo que o grafo deixou no estado (``turno``), monta o
registro, encadeia o hash com o anterior da sessão (guardado no estado, em
``auditoria``), grava primeiro no diário local e envia aos destinos em segundo plano.
Falha no envio não derruba a conversa: fica registrada, e o registro segue no diário.
"""

import asyncio
import logging
from typing import Any

from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.plugins.base_plugin import BasePlugin

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

    async def after_run_callback(
        self, *, invocation_context: InvocationContext
    ) -> None:
        ic = invocation_context
        sessao = ic.session
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
        registro = montar_registro(
            sessao=sessao.id,
            sequencia=anterior["sequencia"] + 1,
            momento=self._relogio(),
            cliente_ref=self._cliente(sessao.state.get("sessao")),
            mensagem=mensagem,
            resposta=respostas[-1] if respostas else "",
            turno=sessao.state.get("turno") or {},
            conhecimento=(
                sessao.state.get("conhecimento") if mexeu_no_conhecimento else None
            ),
            chamadas_llm=[e.author for e in com_texto if e.author in NOS_COM_LLM],
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
