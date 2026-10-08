"""Relatório de latência, tokens e custo por etapa, turno, conversa e intenção (P6.3).

    uv run python -m app.observabilidade.relatorio artifacts/auditoria/diario.jsonl
    uv run python -m app.observabilidade.relatorio --bigquery [--dias 7]

Lê o uso que a auditoria grava (P6.1): a duração do turno e, para cada chamada ao LLM, o
nó, o modelo, a duração e os tokens. O custo vem da tabela de preços, na data de cada
turno. A saída é Markdown, para o terminal ou para o resumo do CI.

Mede o turno inteiro e as chamadas ao LLM. Para ver onde foi o resto do tempo de um turno
(mascaramento, filtro de entrada, sistema de cartões), abra o trace pelo trace_id.
"""

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from app.observabilidade.custo import TabelaDePrecos, carregar_precos, custo_da_chamada


def _intencao(intencao: str | None, desfecho: str | None) -> str:
    # Sem intenção: barrado pelo filtro (rápido) ou interrompido por prazo (lento) não
    # podem cair no mesmo grupo, ou a latência do grupo não quer dizer nada.
    return intencao or f"(sem intenção: {desfecho})"


CONSULTA = """
SELECT sessao, DATE(momento) AS dia, intencao, desfecho, duracao_ms, llm
FROM `{projeto}.auditoria.turnos`
WHERE duracao_ms IS NOT NULL
  AND momento >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @dias DAY)
"""


def turnos_do_diario(caminho: Path) -> list[dict]:
    turnos = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        registro = json.loads(linha)
        uso = registro.get("uso")
        if not uso or uso.get("duracao_ms") is None:
            continue  # registro anterior ao P6.1, sem uso
        turnos.append(
            {
                "sessao": registro["sessao"],
                "dia": datetime.fromisoformat(registro["momento"]).date(),
                "intencao": _intencao(
                    registro.get("intencao"), registro.get("desfecho")
                ),
                "duracao_ms": uso["duracao_ms"],
                "llm": uso["llm"],
            }
        )
    return turnos


def turnos_do_bigquery(dias: int) -> list[dict]:
    from google.cloud import bigquery

    cliente = bigquery.Client()  # projeto das credenciais padrão
    parametros = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("dias", "INT64", dias)]
    )
    consulta = CONSULTA.format(projeto=cliente.project)
    return [
        {
            "sessao": linha["sessao"],
            "dia": linha["dia"],
            "intencao": _intencao(linha["intencao"], linha["desfecho"]),
            "duracao_ms": linha["duracao_ms"],
            "llm": [dict(chamada) for chamada in linha["llm"]],
        }
        for linha in cliente.query(consulta, job_config=parametros).result()
    ]


def percentil(valores: list[float], p: float) -> float:
    """Posição mais próxima: o menor valor com pelo menos p% dos dados até ele."""
    ordenados = sorted(valores)
    return ordenados[max(0, math.ceil(p / 100 * len(ordenados)) - 1)]


def _s(ms: float) -> str:
    return f"{ms / 1000:.1f} s"


def _media(valores: list) -> str:
    validos = [v for v in valores if v is not None]
    return f"{sum(validos) / len(validos):.0f}" if validos else "-"


def relatorio(turnos: list[dict], tabela: TabelaDePrecos) -> str:
    if not turnos:
        return "Nenhum turno com uso registrado.\n"

    custo_turno = []
    chamadas_por_no = defaultdict(list)
    custo_por_no = defaultdict(list)
    sem_contagem = 0
    sem_preco = defaultdict(int)  # modelo -> chamadas
    for turno in turnos:
        total = 0.0
        for chamada in turno["llm"]:
            chamadas_por_no[chamada["no"]].append(chamada)
            try:
                custo = custo_da_chamada(chamada, turno["dia"], tabela)
            except KeyError:
                sem_preco[chamada["modelo"] or "(vazio)"] += 1
                continue
            if custo is None:
                sem_contagem += 1
                continue
            custo_por_no[chamada["no"]].append(custo)
            total += custo
        custo_turno.append(total)

    moeda = tabela.moeda
    dias = sorted(t["dia"] for t in turnos)
    sessoes = defaultdict(float)
    for turno, custo in zip(turnos, custo_turno, strict=True):
        sessoes[turno["sessao"]] += custo
    total = sum(custo_turno)

    linhas = [
        "## Uso e custo",
        "",
        f"{len(turnos)} turnos em {len(sessoes)} conversas, de {dias[0]} a {dias[-1]}. "
        f"Custo estimado em {moeda}, com os preços consultados em "
        f"{tabela.consultado_em} ({tabela.fonte}); só o LLM.",
        "",
        "### Latência",
        "",
        "| Etapa | Chamadas | p50 | p95 | Máx |",
        "|---|---|---|---|---|",
    ]
    duracoes = [t["duracao_ms"] for t in turnos]
    linhas.append(
        f"| turno inteiro | {len(duracoes)} | {_s(percentil(duracoes, 50))} | "
        f"{_s(percentil(duracoes, 95))} | {_s(max(duracoes))} |"
    )
    for no, chamadas in sorted(chamadas_por_no.items()):
        ms = [c["ms"] for c in chamadas if c.get("ms") is not None]
        if ms:
            linhas.append(
                f"| {no} | {len(chamadas)} | {_s(percentil(ms, 50))} | "
                f"{_s(percentil(ms, 95))} | {_s(max(ms))} |"
            )

    linhas += [
        "",
        "### Tokens e custo por chamada (média)",
        "",
        f"| Etapa | Modelo | Entrada | Saída | Pensamento | Custo ({moeda}) |",
        "|---|---|---|---|---|---|",
    ]
    for no, chamadas in sorted(chamadas_por_no.items()):
        modelos = ", ".join(sorted({c["modelo"] for c in chamadas}))
        custos = custo_por_no[no]
        custo = f"{sum(custos) / len(custos):.6f}" if custos else "-"
        # Chamada respondida sem o campo (o Gemini omite pensamento zero) conta como 0;
        # chamada que terminou em erro, sem nenhuma contagem, fica fora da média.
        respondidas = [c for c in chamadas if c.get("tokens_entrada") is not None]
        entrada, saida, pensamento = (
            _media([c.get(campo) or 0 for c in respondidas])
            for campo in ("tokens_entrada", "tokens_saida", "tokens_pensamento")
        )
        linhas.append(
            f"| {no} | {modelos} | {entrada} | {saida} | {pensamento} | {custo} |"
        )

    linhas += [
        "",
        "### Custo",
        "",
        f"- Total: {moeda} {total:.4f}",
        f"- Por mil turnos: {moeda} {1000 * total / len(turnos):.2f}",
        f"- Por conversa (média): {moeda} {total / len(sessoes):.5f}",
    ]
    if sem_contagem:
        linhas.append(
            f"- {sem_contagem} chamada(s) sem contagem de tokens (terminaram em erro): "
            "custo desconhecido, fora do total."
        )
    for modelo, n in sorted(sem_preco.items()):
        linhas.append(
            f"- {n} chamada(s) do modelo `{modelo}`, sem preço em precos.yaml: "
            "fora do total."
        )

    por_intencao = defaultdict(list)
    for turno, custo in zip(turnos, custo_turno, strict=True):
        por_intencao[turno["intencao"]].append((turno["duracao_ms"], custo))
    linhas += [
        "",
        "### Por intenção",
        "",
        f"| Intenção | Turnos | Custo por mil turnos ({moeda}) | p50 | p95 |",
        "|---|---|---|---|---|",
    ]
    for intencao, itens in sorted(por_intencao.items(), key=lambda i: -len(i[1])):
        ms = [d for d, _ in itens]
        custo = 1000 * sum(c for _, c in itens) / len(itens)
        linhas.append(
            f"| {intencao} | {len(itens)} | {custo:.2f} | "
            f"{_s(percentil(ms, 50))} | {_s(percentil(ms, 95))} |"
        )
    return "\n".join(linhas) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("diario", nargs="?", type=Path, help="diário da auditoria")
    parser.add_argument("--bigquery", action="store_true", help="ler do BigQuery")
    parser.add_argument("--dias", type=int, default=7, help="janela no BigQuery")
    args = parser.parse_args()
    if args.bigquery:
        turnos = turnos_do_bigquery(args.dias)
    elif args.diario:
        turnos = turnos_do_diario(args.diario)
    else:
        parser.error("informe o diário ou --bigquery")
    print(relatorio(turnos, carregar_precos()))


if __name__ == "__main__":
    main()
