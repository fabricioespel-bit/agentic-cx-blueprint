"""Registro de auditoria por turno e cadeia de hashes por sessão (P4.2; decisão G3).

Um registro por turno: o que o cliente pediu (já mascarado), o que o agente decidiu e o
que respondeu, sem dado pessoal em claro. Cada registro leva o hash do anterior da mesma
sessão; o próprio hash cobre o conteúdo e esse elo. Alterar, apagar ou reordenar um
registro quebra a cadeia, e ``verificar_cadeia`` aponta onde.

A cadeia detecta adulteração, não a impede: quem impede é o armazenamento (bucket com
retenção travada). A cadeia é por sessão, não global: instâncias do agente em paralelo
não precisam se coordenar.
"""

import hashlib
import json
from datetime import datetime
from typing import Any

from app.orquestrador.textos import desfecho

VERSAO = 3  # 2: uso (duração e chamadas ao LLM); 3: trace_id
GENESE = "0" * 64  # elo do primeiro registro de cada sessão
NOS_COM_LLM = ("classificador", "redator", "revisor")
# Campos de cada chamada ao LLM, iguais no registro e no BigQuery.
CAMPOS_LLM = (
    "no",
    "modelo",
    "ms",
    "tokens_entrada",
    "tokens_saida",
    "tokens_pensamento",
    "tokens_cache",
    "erro",
)


def calcular_hash(registro: dict[str, Any]) -> str:
    conteudo = {k: v for k, v in registro.items() if k != "hash"}
    canonico = json.dumps(
        conteudo, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonico.encode()).hexdigest()


def montar_registro(
    *,
    sessao: str,
    sequencia: int,
    momento: datetime,
    cliente_ref: str | None,
    mensagem: str,
    resposta: str,
    turno: dict[str, Any],
    conhecimento: dict[str, Any] | None,
    chamadas_llm: list[str],
    hash_anterior: str,
    uso: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    registro = {
        "versao": VERSAO,
        "sessao": sessao,
        "sequencia": sequencia,
        "momento": momento.isoformat(),
        "cliente_ref": cliente_ref,
        "mensagem": mensagem,  # já mascarada pelo plugin de mascaramento
        "desfecho": desfecho(resposta),
        "resposta": resposta,
        "intencao": turno.get("intencao"),
        "motivo": turno.get("motivo"),
        "final_descartado": bool(turno.get("final_descartado")),
        "execucao": turno.get("execucao"),
        "encaminhamento": turno.get("encaminhamento"),
        "filtro": turno.get("filtro"),
        "conhecimento": conhecimento,
        "chamadas_llm": chamadas_llm,
        "uso": uso or {"duracao_ms": None, "llm": []},
        "trace_id": trace_id,  # liga o registro ao trace (P6.2)
        "hash_anterior": hash_anterior,
    }
    registro["hash"] = calcular_hash(registro)
    return registro


def verificar_cadeia(registros: list[dict[str, Any]]) -> str | None:
    """Problema no primeiro registro inválido da sessão, ou None se a cadeia está íntegra."""
    anterior = GENESE
    for esperado, registro in enumerate(registros, start=1):
        if registro.get("sequencia") != esperado:
            return f"sequência {esperado}: encontrada {registro.get('sequencia')}"
        if registro.get("hash_anterior") != anterior:
            return f"sequência {esperado}: elo com o anterior quebrado"
        if calcular_hash(registro) != registro.get("hash"):
            return f"sequência {esperado}: conteúdo alterado"
        anterior = registro["hash"]
    return None


def metadados(registro: dict[str, Any], objeto: str) -> dict[str, Any]:
    """Linha do BigQuery: sem a mensagem nem a resposta (minimização)."""
    execucao = registro.get("execucao") or {}
    encaminhamento = registro.get("encaminhamento") or {}
    conhecimento = registro.get("conhecimento") or {}
    uso = registro.get("uso") or {}
    return {
        "versao": registro["versao"],
        "sessao": registro["sessao"],
        "sequencia": registro["sequencia"],
        "momento": registro["momento"],
        "cliente_ref": registro["cliente_ref"],
        "desfecho": registro["desfecho"],
        "intencao": registro["intencao"],
        "motivo": registro["motivo"],
        "final_descartado": registro["final_descartado"],
        "execucao_estado": execucao.get("estado"),
        # Protocolo da execução ou do encaminhamento ao atendimento humano.
        "protocolo": execucao.get("protocolo") or encaminhamento.get("protocolo"),
        "fontes": conhecimento.get("fontes") or [],
        "problemas_verificacao": len(conhecimento.get("problemas") or [])
        + len(conhecimento.get("problemas_revisao") or []),
        "chamadas_llm": registro["chamadas_llm"],
        "duracao_ms": uso.get("duracao_ms"),
        "trace_id": registro.get("trace_id"),
        "llm": [
            {c: chamada.get(c) for c in CAMPOS_LLM} for chamada in uso.get("llm", [])
        ],
        "objeto": objeto,
        "hash": registro["hash"],
        "hash_anterior": registro["hash_anterior"],
    }
