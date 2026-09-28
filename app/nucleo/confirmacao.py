"""Confirmação amarrada aos parâmetros (decisões D4 e D5).

A política emite a confirmação; o executor só aceita a execução que bate com ela. A
confirmação tem texto fixo (vem do catálogo, não do LLM), é vinculada por hash à sessão, à
intenção e aos parâmetros, vale uma única vez e expira em poucos minutos.

Mock: as confirmações ficam em memória; em produção, em armazenamento com expiração.
"""

import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from app.nucleo.catalogo import Intencao

VALIDADE_PADRAO = timedelta(minutes=5)

Relogio = Callable[[], datetime]


def agora_utc() -> datetime:
    return datetime.now(UTC)


class FalhaConfirmacao(StrEnum):
    INEXISTENTE = "confirmacao_inexistente"
    REUTILIZADA = "confirmacao_reutilizada"
    EXPIRADA = "confirmacao_expirada"
    PARAMETROS_DIVERGENTES = "parametros_divergentes"


class ConfirmacaoInvalida(Exception):
    def __init__(self, falha: FalhaConfirmacao):
        super().__init__(falha.value)
        self.falha = falha


@dataclass(frozen=True)
class Confirmacao:
    id: str
    intencao_id: str
    texto: str
    hash_parametros: str
    expira_em: datetime


def hash_parametros(
    sessao_id: str, intencao_id: str, parametros: Mapping[str, Any]
) -> str:
    """Hash da forma canônica: independe da ordem das chaves."""
    canonico = json.dumps(
        {"sessao": sessao_id, "intencao": intencao_id, "parametros": parametros},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonico.encode()).hexdigest()


class Confirmacoes:
    def __init__(
        self, relogio: Relogio = agora_utc, validade: timedelta = VALIDADE_PADRAO
    ):
        self._relogio = relogio
        self._validade = validade
        self._pendentes: dict[str, Confirmacao] = {}
        self._usadas: set[str] = set()

    def emitir(
        self, intencao: Intencao, sessao_id: str, parametros: Mapping[str, Any]
    ) -> Confirmacao:
        if not intencao.texto_confirmacao:
            raise ValueError(f"'{intencao.id}' não tem texto de confirmação")
        confirmacao = Confirmacao(
            id=secrets.token_urlsafe(16),
            intencao_id=intencao.id,
            texto=intencao.texto_confirmacao.format_map(parametros),
            hash_parametros=hash_parametros(sessao_id, intencao.id, parametros),
            expira_em=self._relogio() + self._validade,
        )
        self._pendentes[confirmacao.id] = confirmacao
        return confirmacao

    def consumir(
        self,
        confirmacao_id: str,
        sessao_id: str,
        intencao_id: str,
        parametros: Mapping[str, Any],
    ) -> Confirmacao:
        """Valida e inutiliza a confirmação. Toda tentativa a consome, mesmo a que falha."""
        if confirmacao_id in self._usadas:
            raise ConfirmacaoInvalida(FalhaConfirmacao.REUTILIZADA)
        confirmacao = self._pendentes.pop(confirmacao_id, None)
        if confirmacao is None:
            raise ConfirmacaoInvalida(FalhaConfirmacao.INEXISTENTE)
        self._usadas.add(confirmacao_id)
        if self._relogio() >= confirmacao.expira_em:
            raise ConfirmacaoInvalida(FalhaConfirmacao.EXPIRADA)
        esperado = hash_parametros(sessao_id, intencao_id, parametros)
        if not hmac.compare_digest(esperado, confirmacao.hash_parametros):
            raise ConfirmacaoInvalida(FalhaConfirmacao.PARAMETROS_DIVERGENTES)
        return confirmacao
