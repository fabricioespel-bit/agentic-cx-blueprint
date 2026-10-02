"""Compara os rótulos do juiz com os rótulos humanos (P5.4).

    uv run python tests/eval/calibrar.py artifacts/grade_results/results_<ts>.json

Lê o resultado do ``eval grade`` (métrica ``fidelidade``), o dataset (para ligar o
índice do caso ao id) e ``tests/eval/calibracao/rotulos_humanos.json``. Mostra a
concordância só nos casos com redação, onde o juiz de fato julga.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

PASTA = Path(__file__).parent
DATASET = PASTA / "datasets" / "conhecimento.json"
HUMANOS = PASTA / "calibracao" / "rotulos_humanos.json"


def rotulos_do_juiz(resultados: dict, ids: list[str]) -> dict[str, tuple[str, str]]:
    juiz = {}
    for caso in resultados["eval_case_results"]:
        metrica = caso["response_candidate_results"][0]["metric_results"]["fidelidade"]
        explicacao = metrica.get("explanation") or ""
        achado = re.match(r"rotulo: (\w+);?\s*(.*)", explicacao, flags=re.DOTALL)
        rotulo, motivo = achado.groups() if achado else ("erro", explicacao)
        juiz[ids[caso["eval_case_index"]]] = (rotulo, motivo)
    return juiz


def main(caminho: str) -> None:
    ids = [c["eval_case_id"] for c in json.loads(DATASET.read_text())["eval_cases"]]
    humanos = {c["id"]: c["rotulo"] for c in json.loads(HUMANOS.read_text())["casos"]}
    juiz = rotulos_do_juiz(json.loads(Path(caminho).read_text()), ids)
    julgados = [i for i in ids if juiz[i][0] != "nao_se_aplica"]
    iguais = [i for i in julgados if juiz[i][0] == humanos[i]]
    print(f"Casos com redação julgados: {len(julgados)} de {len(ids)}")
    print(f"Concordância com os rótulos humanos: {len(iguais)}/{len(julgados)}\n")
    print("| Caso | Humano | Juiz | Motivo do juiz |")
    print("|---|---|---|---|")
    for i in julgados:
        marca = "" if i in iguais else " ⚠"
        print(f"| {i}{marca} | {humanos[i]} | {juiz[i][0]} | {juiz[i][1]} |")
    pares = Counter((humanos[i], juiz[i][0]) for i in julgados)
    print("\nPares (humano → juiz):", dict(pares))


if __name__ == "__main__":
    main(sys.argv[1])
