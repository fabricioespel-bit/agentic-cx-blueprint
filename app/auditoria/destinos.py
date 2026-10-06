"""Onde a trilha é gravada (P4.2).

- ``DestinoArquivo``: JSONL local, só acréscimo. Diário de toda a trilha no protótipo
  (gravado antes do envio) e destino dos testes.
- ``DestinoGoogle``: registro completo no Cloud Storage (bucket com retenção travada,
  objeto gravado uma vez só) e metadados no BigQuery, ambos em southamerica-east1.
"""

import json
from pathlib import Path
from typing import Any, Protocol

from app.auditoria.registro import metadados


class Destino(Protocol):
    def gravar(self, registro: dict[str, Any]) -> None: ...


class DestinoArquivo:
    def __init__(self, caminho: Path):
        self._caminho = caminho

    def gravar(self, registro: dict[str, Any]) -> None:
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._caminho.open("a", encoding="utf-8") as arquivo:
            arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")

    def ler(self) -> list[dict[str, Any]]:
        if not self._caminho.exists():
            return []
        with self._caminho.open(encoding="utf-8") as arquivo:
            return [json.loads(linha) for linha in arquivo if linha.strip()]


class DestinoGoogle:
    def __init__(
        self, projeto: str, bucket: str, tabela: str, storage=None, bigquery=None
    ):
        # Clientes criados na primeira gravação: importar o agente não exige credenciais.
        self._projeto = projeto
        self._bucket_nome = bucket
        self._tabela = tabela
        self._storage = storage
        self._bigquery = bigquery

    def gravar(self, registro: dict[str, Any]) -> None:
        if self._storage is None:
            from google.cloud import bigquery, storage

            self._storage = storage.Client(project=self._projeto)
            self._bigquery = bigquery.Client(project=self._projeto)
        dia = registro["momento"][:10]
        nome = f"{dia}/{registro['sessao']}/{registro['sequencia']:06d}.json"
        blob = self._storage.bucket(self._bucket_nome).blob(nome)
        # if_generation_match=0: só cria; se o objeto já existir, falha (grava uma vez).
        blob.upload_from_string(
            json.dumps(registro, ensure_ascii=False),
            content_type="application/json",
            if_generation_match=0,
        )
        objeto = f"gs://{self._bucket_nome}/{nome}"
        erros = self._bigquery.insert_rows_json(
            self._tabela, [metadados(registro, objeto)]
        )
        if erros:
            raise RuntimeError(f"BigQuery recusou o registro: {erros}")
