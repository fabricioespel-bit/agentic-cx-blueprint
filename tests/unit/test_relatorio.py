"""Relatório de uso e custo (P6.3). Turnos montados à mão; sem BigQuery."""

import json
from datetime import date

from app.observabilidade.custo import carregar_precos
from app.observabilidade.relatorio import percentil, relatorio, turnos_do_diario

TABELA = carregar_precos()
DIA = date(2026, 10, 7)


def _chamada(no, entrada, saida, pensamento, ms=1000, modelo="gemini-3.8-flash"):
    return {
        "no": no,
        "modelo": modelo,
        "ms": ms,
        "tokens_entrada": entrada,
        "tokens_saida": saida,
        "tokens_pensamento": pensamento,
        "tokens_cache": None,
    }


# Classificador: (1000 x 0,75 + 400 x 3,75) / 1 milhão = 0,00225.
# Redator: (2000 x 0,75 + 1000 x 3,75) / 1 milhão = 0,00525.
TURNOS = [
    {
        "sessao": "a",
        "dia": DIA,
        "intencao": "consultar_limite",
        "duracao_ms": 3000,
        "llm": [_chamada("classificador", 1000, 100, 300)],
    },
    {
        "sessao": "a",
        "dia": DIA,
        "intencao": "duvida_produtos_tarifas",
        "duracao_ms": 9000,
        "llm": [
            _chamada("classificador", 1000, 100, 300),
            _chamada("redator", 2000, 100, 900),
        ],
    },
    {
        "sessao": "b",
        "dia": DIA,
        "intencao": "(sem intenção: barrado)",
        "duracao_ms": 300,
        "llm": [],
    },
    {
        "sessao": "b",
        "dia": DIA,
        "intencao": "(sem intenção: interrompido)",
        "duracao_ms": 31000,
        "llm": [
            {
                **_chamada("classificador", None, None, None, ms=30000),
                "erro": "TimeoutError",
            },
            _chamada("classificador", 10, 1, 1, ms=None, modelo=""),
        ],
    },
]


def test_percentil_por_posicao_mais_proxima():
    valores = list(range(1, 21))  # 1 a 20
    assert percentil(valores, 50) == 10
    assert percentil(valores, 95) == 19
    assert percentil([7], 95) == 7


def test_relatorio_soma_custo_por_turno_conversa_e_intencao():
    texto = relatorio(TURNOS, TABELA)
    assert "4 turnos em 2 conversas" in texto
    # (0,00225 + 0,00225 + 0,00525) / 4 turnos x 1000
    assert "Por mil turnos: USD 2.44" in texto
    assert "| consultar_limite | 1 | 2.25 |" in texto
    assert "| duvida_produtos_tarifas | 1 | 7.50 |" in texto


def test_barrado_e_interrompido_ficam_em_grupos_separados():
    texto = relatorio(TURNOS, TABELA)
    assert "| (sem intenção: barrado) | 1 | 0.00 | 0.3 s | 0.3 s |" in texto
    assert "| (sem intenção: interrompido) | 1 | 0.00 | 31.0 s | 31.0 s |" in texto


def test_custo_desconhecido_aparece_e_fica_fora_do_total():
    texto = relatorio(TURNOS, TABELA)
    assert "1 chamada(s) sem contagem de tokens" in texto
    assert "1 chamada(s) do modelo `(vazio)`, sem preço" in texto


def test_diario_ignora_registro_sem_uso_e_rotula_pelo_desfecho(tmp_path):
    diario = tmp_path / "diario.jsonl"
    antigo = {"sessao": "x", "momento": "2026-10-01T10:00:00+00:00", "intencao": "c"}
    barrado = {
        "sessao": "y",
        "momento": "2026-10-07T10:00:00+00:00",
        "intencao": None,
        "desfecho": "barrado",
        "uso": {"duracao_ms": 300, "llm": []},
    }
    diario.write_text(
        "\n".join(json.dumps(r) for r in (antigo, barrado)) + "\n", encoding="utf-8"
    )
    [turno] = turnos_do_diario(diario)
    assert turno["intencao"] == "(sem intenção: barrado)"
    assert turno["dia"] == date(2026, 10, 7)


def test_sem_turnos():
    assert relatorio([], TABELA) == "Nenhum turno com uso registrado.\n"
