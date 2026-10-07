"""Resumo em Markdown do último resultado de avaliação (P5).

    uv run python tests/eval/resumo.py [artifacts/grade_results/results_<ts>.json]

Sem argumento, usa o resultado mais recente. No CI, a saída vai para o resumo da
execução do GitHub Actions. Lê o dataset para ligar cada caso ao grupo.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

DATASET = Path(__file__).parent / "datasets" / "conhecimento.json"
RESULTADOS = Path("artifacts/grade_results")
APROVACAO = ("comportamento", "conteudo")


def metricas_por_caso(resultados: dict) -> dict[str, dict]:
    """Métricas de cada caso pelo id.

    O ``eval_case_index`` aponta para os casos que o ``eval grade`` recebeu
    (``evaluation_dataset``), não para o dataset: caso que falha na execução fica de
    fora, e os seguintes mudam de posição.
    """
    avaliados = resultados["evaluation_dataset"][0]["eval_cases"]
    return {
        avaliados[item["eval_case_index"]]["eval_case_id"]: item[
            "response_candidate_results"
        ][0]["metric_results"]
        for item in resultados["eval_case_results"]
    }


def resumo(resultados: dict, casos: list[dict]) -> str:
    linhas = ["## Avaliação do agente", ""]
    por_caso = metricas_por_caso(resultados)

    nomes = sorted({m for metricas in por_caso.values() for m in metricas})
    linhas += ["| Métrica | Média |", "|---|---|"]
    for nome in nomes:
        notas = [m[nome]["score"] for m in por_caso.values() if nome in m]
        linhas.append(f"| `{nome}` | {sum(notas) / len(notas):.2f} |")

    grupos = defaultdict(lambda: [0, 0])
    falhas = []
    nao_executados = []
    for caso in casos:
        grupo = caso["esperado"]["grupo"]
        if caso["eval_case_id"] not in por_caso:
            grupos[grupo][1] += 1
            nao_executados.append(f"- `{caso['eval_case_id']}` ({grupo})")
            continue
        metricas = por_caso[caso["eval_case_id"]]
        aprovado = all(metricas.get(n, {}).get("score") == 1 for n in APROVACAO)
        grupos[grupo][0] += aprovado
        grupos[grupo][1] += 1
        fidelidade = metricas.get("fidelidade", {}).get("score", 1)
        if not aprovado or fidelidade < 1:
            motivos = [
                f"{n}: {metricas[n]['explanation']}"
                for n in (*APROVACAO, "fidelidade")
                if n in metricas and metricas[n]["score"] < 1
            ]
            falhas.append(f"- `{caso['eval_case_id']}` ({grupo}): {'; '.join(motivos)}")

    linhas += ["", "| Grupo | Aprovados |", "|---|---|"]
    linhas += [f"| {g} | {a}/{t} |" for g, (a, t) in grupos.items()]
    linhas += ["", "### Casos com problema", "", *(falhas or ["Nenhum."])]
    if nao_executados:
        linhas += [
            "",
            "### Casos não executados",
            "",
            "Falharam na execução (ex.: tempo esgotado) e ficaram sem nota; contam como "
            "não aprovados.",
            "",
            *nao_executados,
        ]
    linhas += [
        "",
        "Aprovado = `comportamento` e `conteudo` com nota 1. Os casos do grupo `lacuna` "
        "falham de propósito enquanto a busca for lexical.",
    ]
    return "\n".join(linhas) + "\n"


if __name__ == "__main__":
    caminho = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else max(RESULTADOS.glob("results_*.json"), key=lambda p: p.stat().st_mtime)
    )
    casos = json.loads(DATASET.read_text(encoding="utf-8"))["eval_cases"]
    print(resumo(json.loads(caminho.read_text(encoding="utf-8")), casos))
