"""Confere, pelo diário da auditoria, que nenhum dado pessoal dos casos entrou no agente.

    uv run python tests/eval/conferir_privacidade.py artifacts/auditoria/diario.jsonl

Complementa a métrica ``sem_dado_pessoal``: o ``eval grade`` descarta os eventos que só
mudam o estado da sessão antes de chamar as métricas, então a métrica vê as saídas dos
LLMs e a resposta, mas não o texto que o agente recebeu e gravou. O diário registra
exatamente esse texto (a mensagem depois do mascaramento), um registro por turno.

Rode com um diário que só tenha a execução a conferir (no CI, ele nasce vazio). Sai com
código 1 se algum dado aparecer.
"""

import json
import sys
from pathlib import Path

DATASET = Path(__file__).parent / "datasets" / "conhecimento.json"


def vazamentos(registros: list[dict], casos: list[dict]) -> list[str]:
    """Dados pessoais dos casos que aparecem em algum registro do diário."""
    dados = {
        dado: caso["eval_case_id"]
        for caso in casos
        for dado in caso["esperado"].get("dados_pessoais", [])
    }
    achados = []
    for registro in registros:
        texto = json.dumps(registro, ensure_ascii=False)
        for dado, caso in dados.items():
            if dado in texto:
                achados.append(f"{caso}: '{dado}' na sessão {registro.get('sessao')}")
    return achados


if __name__ == "__main__":
    diario = Path(sys.argv[1])
    registros = [
        json.loads(linha)
        for linha in diario.read_text(encoding="utf-8").splitlines()
        if linha.strip()
    ]
    casos = json.loads(DATASET.read_text(encoding="utf-8"))["eval_cases"]
    achados = vazamentos(registros, casos)
    print(f"{len(registros)} registros conferidos")
    print("\n".join(achados) if achados else "nenhum dado pessoal no diário")
    sys.exit(1 if achados else 0)
