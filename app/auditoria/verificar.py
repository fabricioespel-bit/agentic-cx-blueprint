"""Verifica a trilha de auditoria de um dia (P4.2).

    uv run python -m app.auditoria.verificar 2026-10-06

Para cada sessão do dia: lê os registros completos do Cloud Storage, confere a cadeia de
hashes e confere que o BigQuery tem as mesmas linhas, com os mesmos hashes. Só lê; quem
roda precisa de leitura no bucket e na tabela (a conta do agente só grava).
"""

import json
import os
import sys
from collections import defaultdict

from dotenv import load_dotenv
from google.cloud import bigquery, storage

from app.auditoria.registro import verificar_cadeia


def verificar(projeto: str, bucket: str, tabela: str, dia: str) -> list[str]:
    """Problemas encontrados no dia; lista vazia quer dizer trilha íntegra."""
    registros = defaultdict(list)
    for blob in storage.Client(project=projeto).list_blobs(bucket, prefix=f"{dia}/"):
        registro = json.loads(blob.download_as_text())
        registros[registro["sessao"]].append(registro)

    consulta = (
        # "hash" é palavra reservada no SQL do BigQuery: a coluna vai entre crases.
        f"SELECT sessao, sequencia, `hash` FROM `{tabela}` "
        "WHERE DATE(momento) = @dia ORDER BY sessao, sequencia"
    )
    parametros = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("dia", "DATE", dia)]
    )
    linhas = defaultdict(set)
    for linha in bigquery.Client(project=projeto).query(consulta, parametros).result():
        linhas[linha.sessao].add((linha.sequencia, linha.hash))

    problemas = []
    for sessao in sorted(registros.keys() | linhas.keys()):
        cadeia = sorted(registros.get(sessao, []), key=lambda r: r["sequencia"])
        if erro := verificar_cadeia(cadeia):
            problemas.append(f"{sessao}: {erro}")
        no_bucket = {(r["sequencia"], r["hash"]) for r in cadeia}
        if no_bucket != linhas.get(sessao, set()):
            problemas.append(f"{sessao}: bucket e BigQuery divergem")
    total = sum(len(c) for c in registros.values())
    print(f"{dia}: {len(registros)} sessões, {total} registros no bucket")
    return problemas


if __name__ == "__main__":
    load_dotenv()
    projeto = os.environ["GOOGLE_CLOUD_PROJECT"]
    problemas = verificar(
        projeto,
        os.environ.get("AUDITORIA_BUCKET", f"{projeto}-auditoria"),
        os.environ.get("AUDITORIA_TABELA", f"{projeto}.auditoria.turnos"),
        sys.argv[1],
    )
    print("\n".join(problemas) if problemas else "trilha íntegra")
    sys.exit(1 if problemas else 0)
