"""Custo estimado a partir do uso na auditoria (P6.3). Sem rede: só a tabela de preços."""

import re
from datetime import date
from pathlib import Path

import pytest

from app.observabilidade.custo import carregar_precos, custo_da_chamada

TABELA = carregar_precos()
HOJE = date(2026, 10, 7)
CHAMADA = {
    "modelo": "gemini-3.8-flash",
    "tokens_entrada": 1000,
    "tokens_cache": 200,
    "tokens_saida": 100,
    "tokens_pensamento": 300,
}


def test_tabela_cobre_os_modelos_do_agente():
    # Trocar o modelo em app/agent.py sem pôr o preço quebra aqui, não no relatório.
    codigo = Path("app/agent.py").read_text(encoding="utf-8")
    modelos = set(re.findall(r'"(gemini-[\w.-]+)"', codigo))
    assert modelos
    assert modelos <= set(TABELA.modelos)


def test_pensamento_e_saida_e_cache_tem_desconto():
    # 800 de entrada a 0,75; 200 de cache a 0,075; 100 + 300 de saída a 3,75 (por milhão).
    esperado = (800 * 0.75 + 200 * 0.075 + 400 * 3.75) / 1_000_000
    assert custo_da_chamada(CHAMADA, HOJE, TABELA) == pytest.approx(esperado)


def test_preco_vigente_na_data_do_turno():
    antes = custo_da_chamada(CHAMADA, date(2026, 12, 31), TABELA)
    depois = custo_da_chamada(CHAMADA, date(2027, 1, 1), TABELA)
    assert depois == pytest.approx(2 * antes)  # o Flash dobra em 2027


def test_chamada_sem_tokens_fica_sem_custo():
    erro = {
        "modelo": "gemini-3.8-flash",
        "tokens_entrada": None,
        "erro": "TimeoutError",
    }
    assert custo_da_chamada(erro, HOJE, TABELA) is None


def test_modelo_sem_preco_falha():
    with pytest.raises(KeyError, match="gemini-9"):
        custo_da_chamada({**CHAMADA, "modelo": "gemini-9"}, HOJE, TABELA)


def test_preco_vazio_e_recusado(tmp_path):
    arquivo = tmp_path / "precos.yaml"
    arquivo.write_text(
        "moeda: USD\nconsultado_em: 2026-10-07\nfonte: x\n"
        "modelos:\n  m:\n    - {a_partir_de: null, entrada: 1, entrada_cache: null, saida: 2}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="entrada_cache"):
        carregar_precos(arquivo)
