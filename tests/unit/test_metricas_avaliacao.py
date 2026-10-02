"""Métricas de código da avaliação (tests/eval/metricas.py). Sem LLM."""

import runpy
from pathlib import Path

import pytest

from app.orquestrador import textos

M = runpy.run_path(str(Path(__file__).parents[1] / "eval" / "metricas.py"))


def caso(texto: str, autores=(), **esperado) -> dict:
    eventos = [{"author": a} for a in ("user", *autores)]
    return {
        "response": {"role": "model", "parts": [{"text": texto}]},
        "agent_data": {"turns": [{"events": eventos}]},
        "esperado": esperado,
    }


RESPOSTA = "A anuidade é de 12 parcelas de R$ 19,90.\n\n" + textos.FONTES.format(
    lista="Cartão Exemplo Clássico, Anuidade"
)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        (RESPOSTA, "responde"),
        (textos.SEM_FONTE, "recusa"),
        (textos.FORA_DE_ESCOPO, "fora_de_escopo"),
        (textos.PERGUNTA_CARTAO.format(opcoes="1234 (crédito)"), "pergunta_cartao"),
        (textos.NEGACAO_PADRAO, "nega"),
        *[(t, "nega") for t in textos.NEGACOES.values()],
        *[(t, "nega") for t in textos.NEGACOES_POR_INTENCAO.values()],
        ("Pronto: o cartão final 1234 está bloqueado.", "outro"),
    ],
)
def test_reconhece_os_textos_fixos_do_agente(texto, esperado):
    # Se um texto de textos.py mudar, este teste aponta a cópia desatualizada.
    assert M["comportamento_observado"](texto) == esperado


def test_rodape_igual_ao_do_agente():
    assert textos.FONTES.startswith(M["RODAPE_FONTES"])


def test_comportamento_aceita_qualquer_um_da_lista():
    aceitos = ["recusa", "fora_de_escopo"]
    assert (
        M["comportamento"](caso(textos.SEM_FONTE, comportamento=aceitos))["score"] == 1
    )
    reprovado = M["comportamento"](caso(RESPOSTA, comportamento=aceitos))
    assert reprovado["score"] == 0
    assert "observado: responde" in reprovado["explanation"]


def test_comportamento_aceita_texto_simples():
    resultado = M["comportamento"](caso(textos.SEM_FONTE, comportamento="recusa"))
    assert resultado == {
        "score": 1.0,
        "explanation": "observado: recusa; aceitos: recusa",
    }


def test_conteudo_aprova_valor_e_fonte_presentes():
    resultado = M["conteudo"](
        caso(
            RESPOSTA,
            valores=["R$ 19,90"],
            fontes=["Cartão Exemplo Clássico, Anuidade"],
        )
    )
    assert resultado == {"score": 1.0, "explanation": "ok"}


def test_conteudo_aponta_cada_problema():
    resultado = M["conteudo"](
        caso(
            RESPOSTA,
            valores=["R$ 49,90"],
            fontes=["Cartão Exemplo Platinum, Anuidade"],
            nao_deve_conter=["r$ 19,90"],
        )
    )
    assert resultado["score"] == 0
    assert resultado["explanation"] == (
        "falta o valor R$ 49,90; falta a fonte Cartão Exemplo Platinum, Anuidade; "
        "contém 'r$ 19,90'"
    )


def test_fonte_so_conta_no_rodape():
    # O nome do produto no corpo da resposta não é citação.
    texto = "O Cartão Exemplo Clássico, Anuidade baixa."
    resultado = M["conteudo"](caso(texto, fontes=["Cartão Exemplo Clássico, Anuidade"]))
    assert resultado["score"] == 0


def test_chamadas_llm_conta_so_os_nos_com_modelo():
    autores = ("classificador", "redator", "revisor", "agentic_cx_blueprint")
    resultado = M["chamadas_llm"](caso(RESPOSTA, autores))
    assert resultado == {"score": 3.0, "explanation": "classificador, redator, revisor"}
