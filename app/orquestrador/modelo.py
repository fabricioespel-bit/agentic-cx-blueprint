"""Chamada ao Gemini com prazo e uma repetição.

A biblioteca do Gemini repete erros de servidor e de cota, mas não espera com prazo: na
avaliação, uma chamada ficou sem resposta por cerca de 2 minutos e travou o turno. A
latência tem cauda longa (a mesma pergunta ao classificador levou 33 s numa chamada e
cerca de 2 s nas seguintes), então o prazo vem com uma repetição, que costuma ser rápida.

O prazo fica aqui, na chamada ao modelo, e não no nó do grafo: o nó do ADK publica um
evento de erro a cada tentativa que falha, mesmo quando vai repetir, e o cliente veria
um erro antes da resposta certa. Aqui a tentativa descartada não aparece; só a falha
final sobe, e o turno fica na auditoria como interrompido.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator

from google.adk.models import Gemini, LlmRequest, LlmResponse

logger = logging.getLogger(__name__)


class GeminiComPrazo(Gemini):
    prazo: float = 15.0  # segundos por tentativa
    tentativas: int = 2

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        for tentativa in range(1, self.tentativas + 1):
            try:
                async with asyncio.timeout(self.prazo):
                    respostas = [
                        r
                        async for r in super().generate_content_async(
                            llm_request, stream
                        )
                    ]
                break
            except TimeoutError:
                if tentativa == self.tentativas:
                    raise
                logger.warning(
                    "%s sem resposta em %.0f s; repetindo (tentativa %d de %d)",
                    self.model,
                    self.prazo,
                    tentativa + 1,
                    self.tentativas,
                )
        for resposta in respostas:
            yield resposta
