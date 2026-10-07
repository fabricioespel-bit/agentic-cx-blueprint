"""Prazo e repetição na chamada ao Gemini. Sem LLM: a chamada do ADK é trocada por uma falsa."""

import asyncio

import pytest
from google.adk.models import Gemini, LlmRequest, LlmResponse

from app.orquestrador.modelo import GeminiComPrazo


@pytest.fixture
def chamadas(monkeypatch):
    """Troca a chamada do ADK por uma que trava nas primeiras ``travar`` vezes."""
    estado = {"travar": 0, "feitas": 0}

    async def falsa(self, llm_request, stream=False):
        estado["feitas"] += 1
        if estado["feitas"] <= estado["travar"]:
            await asyncio.sleep(60)
        yield LlmResponse(partial=False)

    monkeypatch.setattr(Gemini, "generate_content_async", falsa)
    return estado


def responder(modelo: GeminiComPrazo) -> list[LlmResponse]:
    async def _chamar():
        return [r async for r in modelo.generate_content_async(LlmRequest())]

    return asyncio.run(_chamar())


def test_sem_resposta_no_prazo_repete_sem_aparecer_ao_cliente(chamadas, caplog):
    chamadas["travar"] = 1
    respostas = responder(GeminiComPrazo(model="m", prazo=0.1))
    assert len(respostas) == 1  # só a resposta da segunda tentativa
    assert chamadas["feitas"] == 2
    assert "repetindo (tentativa 2 de 2)" in caplog.text


def test_sem_resposta_nas_duas_tentativas_falha(chamadas):
    chamadas["travar"] = 2
    with pytest.raises(TimeoutError):
        responder(GeminiComPrazo(model="m", prazo=0.1))
    assert chamadas["feitas"] == 2


def test_resposta_no_prazo_nao_repete(chamadas):
    assert len(responder(GeminiComPrazo(model="m", prazo=0.1))) == 1
    assert chamadas["feitas"] == 1
