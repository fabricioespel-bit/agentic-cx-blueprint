"""Plugin do ADK que mascara a mensagem do cliente antes de tudo (P4.1).

Faz o papel do gateway de canal, que no protótipo não existe: roda antes de a mensagem
ser gravada na sessão e antes de o grafo começar.
"""

import asyncio

from google.adk.agents.invocation_context import InvocationContext
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

from app.guardrails.mascaramento import Mascarador


class PluginMascaramento(BasePlugin):
    def __init__(self, mascarador: Mascarador):
        super().__init__(name="mascaramento")
        self._mascarador = mascarador

    async def on_user_message_callback(
        self,
        *,
        invocation_context: InvocationContext,
        user_message: types.Content,
    ) -> types.Content | None:
        for parte in user_message.parts or []:
            if parte.text:
                # Fora do loop de eventos: o SDP é uma chamada de rede.
                parte.text = await asyncio.to_thread(
                    self._mascarador.mascarar, parte.text
                )
        # Altera a própria mensagem e devolve None. O runner do ADK guarda a mensagem
        # original como entrada do grafo antes deste callback: uma mensagem nova iria
        # mascarada para a sessão, mas o classificador veria a original (não mascarada).
        return None
