"""Métricas de código da avaliação (tests/eval/metricas.py). Sem LLM."""

import json
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
        (textos.NUMERO_DE_CARTAO, "aviso_cartao"),
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


# Juiz (tests/eval/juiz.py): só as partes sem LLM.
J = runpy.run_path(str(Path(__file__).parents[1] / "eval" / "juiz.py"))
G = runpy.run_path(str(Path(__file__).parents[1] / "eval" / "gerar_corpus_juiz.py"))


def test_corpus_do_juiz_atualizado():
    # Se falhar: uv run python tests/eval/gerar_corpus_juiz.py
    arquivo = Path(__file__).parents[1] / "eval" / "corpus_juiz.json"
    assert json.loads(arquivo.read_text(encoding="utf-8")) == G["trechos_preenchidos"]()


def test_juiz_le_as_fontes_do_rodape():
    resposta = textos.FONTES.format(
        lista="Cartão Exemplo Clássico, Anuidade; Tarifas de serviços dos cartões, "
        "Segunda via do cartão"
    )
    assert J["fontes_citadas"]("Texto.\n\n" + resposta) == [
        "Cartão Exemplo Clássico, Anuidade",
        "Tarifas de serviços dos cartões, Segunda via do cartão",
    ]


def test_juiz_nao_julga_texto_fixo():
    resultado = J["evaluate"](
        {"prompt": "Qual ação devo comprar?", "response": textos.FORA_DE_ESCOPO}
    )
    assert resultado["explanation"].startswith("rotulo: nao_se_aplica")


def test_juiz_ve_a_resposta_sem_rodape_e_o_trecho_preenchido():
    pedido = J["montar_pedido"](
        "Qual a anuidade?",
        RESPOSTA,
        {"Cartão Exemplo Clássico, Anuidade": "texto do trecho"},
    )
    assert "Fontes consultadas" not in pedido
    assert "[Cartão Exemplo Clássico, Anuidade]\ntexto do trecho" in pedido


def test_nota_do_juiz_segue_a_gravidade():
    notas = {r.value: J["NOTAS"].get(r, 0.0) for r in J["Rotulo"]}
    assert notas == {
        "ok": 1.0,
        "excesso": 0.5,
        "incompleto": 0.0,
        "nao_responde": 0.0,
        "infiel": 0.0,
    }


def test_resumo_agrupa_e_lista_os_casos_com_problema():
    resumo = runpy.run_path(str(Path(__file__).parents[1] / "eval" / "resumo.py"))
    casos = [
        {"eval_case_id": "a", "esperado": {"grupo": "responde"}},
        {"eval_case_id": "b", "esperado": {"grupo": "responde"}},
    ]
    ok = {"score": 1.0, "explanation": "ok"}
    resultados = {
        "eval_case_results": [
            {
                "eval_case_index": 0,
                "response_candidate_results": [
                    {"metric_results": {"comportamento": ok, "conteudo": ok}}
                ],
            },
            {
                "eval_case_index": 1,
                "response_candidate_results": [
                    {
                        "metric_results": {
                            "comportamento": ok,
                            "conteudo": ok,
                            "fidelidade": {
                                "score": 0.5,
                                "explanation": "rotulo: excesso",
                            },
                        }
                    }
                ],
            },
        ]
    }
    texto = resumo["resumo"](resultados, casos)
    assert "| responde | 2/2 |" in texto
    assert "- `b` (responde): fidelidade: rotulo: excesso" in texto
    assert "`a`" not in texto


def test_sem_dado_pessoal_procura_no_trace_e_na_resposta():
    vazou = caso(
        "Seu CPF 529.982.247-25 foi recebido.", dados_pessoais=["529.982.247-25"]
    )
    assert M["sem_dado_pessoal"](vazou) == {
        "score": 0.0,
        "explanation": "vazou: 529.982.247-25",
    }
    limpo = caso("De qual cartão?", dados_pessoais=["529.982.247-25"])
    assert M["sem_dado_pessoal"](limpo)["score"] == 1.0
    assert M["sem_dado_pessoal"](caso("ok"))["explanation"] == "nada a conferir"


def test_conferir_privacidade_acha_dado_no_diario():
    conferir = runpy.run_path(
        str(Path(__file__).parents[1] / "eval" / "conferir_privacidade.py")
    )
    casos = [
        {"eval_case_id": "nome", "esperado": {"dados_pessoais": ["Maria Aparecida"]}},
        {"eval_case_id": "sem_dados", "esperado": {}},
    ]
    vazou = {"sessao": "s1", "mensagem": "Sou a Maria Aparecida dos Santos"}
    mascarado = {"sessao": "s2", "mensagem": "Sou a [NOME]"}
    assert conferir["vazamentos"]([vazou, mascarado], casos) == [
        "nome: 'Maria Aparecida' na sessão s1"
    ]
    assert conferir["vazamentos"]([mascarado], casos) == []
