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
import re
from datetime import datetime
from typing import Any

from app.orquestrador import textos

VERSAO = 1
GENESE = "0" * 64  # elo do primeiro registro de cada sessão
NOS_COM_LLM = ("classificador", "redator", "revisor")
RODAPE_FONTES = textos.FONTES.split("{")[0]


def _modelo(texto: str) -> re.Pattern:
    """Texto fixo com campos ({final}, {texto}...) vira expressão regular."""
    partes = re.split(r"\{[^}]*\}", texto)
    return re.compile(".*".join(re.escape(p) for p in partes), flags=re.DOTALL)


# Desfecho reconhecido pelo texto fixo que o cliente recebeu (app/orquestrador/textos.py).
DESFECHOS = [
    (_modelo(textos.NUMERO_DE_CARTAO), "aviso_cartao"),
    (_modelo(textos.SEM_FONTE), "sem_fonte"),
    (_modelo(textos.FORA_DE_ESCOPO), "fora_de_escopo"),
    (_modelo(textos.PERGUNTA_CARTAO), "pergunta_cartao"),
    (_modelo(textos.CONFIRMACAO), "confirmacao_pedida"),
    (_modelo(textos.CANCELADO), "cancelado"),
    (_modelo(textos.BLOQUEADO), "executado"),
    (_modelo(textos.EM_VERIFICACAO), "execucao_incerta"),
    (_modelo(textos.JA_BLOQUEADO), "ja_bloqueado"),
    (_modelo(textos.CONFIRMACAO_INVALIDA), "confirmacao_invalida"),
    (_modelo(textos.CARTAO_NAO_ENCONTRADO), "cartao_nao_encontrado"),
    (_modelo(textos.LIMITE), "consulta"),
    (_modelo(textos.CARTOES), "consulta"),
    (_modelo(textos.FALHA), "falha"),
    *[
        (_modelo(t), "negado")
        for t in (
            textos.NEGACAO_PADRAO,
            *textos.NEGACOES.values(),
            *textos.NEGACOES_POR_INTENCAO.values(),
        )
    ],
]


def desfecho(resposta: str) -> str:
    if RODAPE_FONTES in resposta:
        return "respondido"
    for modelo, nome in DESFECHOS:
        if modelo.fullmatch(resposta):
            return nome
    return "outro"


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
        "conhecimento": conhecimento,
        "chamadas_llm": chamadas_llm,
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
    conhecimento = registro.get("conhecimento") or {}
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
        "protocolo": execucao.get("protocolo"),
        "fontes": conhecimento.get("fontes") or [],
        "problemas_verificacao": len(conhecimento.get("problemas") or [])
        + len(conhecimento.get("problemas_revisao") or []),
        "chamadas_llm": registro["chamadas_llm"],
        "objeto": objeto,
        "hash": registro["hash"],
        "hash_anterior": registro["hash_anterior"],
    }
