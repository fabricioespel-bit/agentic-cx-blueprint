"""Registro de execuções e idempotência (decisão D6).

A chave de idempotência é o id da confirmação: cada confirmação autoriza no máximo uma
execução. Antes de executar de novo, consulta-se o registro. Execução com desfecho
desconhecido (timeout) fica "incerta" até a consulta de estado no sistema de origem
resolver; o assistente nunca afirma sucesso de execução incerta.

Mock: registro em memória; em produção, banco dedicado com outbox de eventos (D7).
"""

import secrets
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from app.nucleo.confirmacao import Relogio, agora_utc

FUSO = ZoneInfo("America/Sao_Paulo")


class Estado(StrEnum):
    PENDENTE = "pendente"
    CONCLUIDA = "concluida"
    INCERTA = "incerta"


@dataclass(frozen=True)
class Execucao:
    chave: str
    cliente_ref: str
    intencao_id: str
    parametros: Mapping[str, Any]
    estado: Estado
    iniciada_em: datetime
    protocolo: str


class ChaveEmConflito(ValueError):
    """Chave reapresentada com cliente, intenção ou parâmetros diferentes, ou já iniciada."""


class RegistroExecucoes:
    def __init__(self, relogio: Relogio = agora_utc):
        self._relogio = relogio
        self._execucoes: dict[str, Execucao] = {}

    def obter(
        self,
        chave: str,
        cliente_ref: str,
        intencao_id: str,
        parametros: Mapping[str, Any],
    ) -> Execucao | None:
        """Execução já registrada com esta chave; a chave só vale para os mesmos dados."""
        execucao = self._execucoes.get(chave)
        if execucao is None:
            return None
        if (execucao.cliente_ref, execucao.intencao_id, dict(execucao.parametros)) != (
            cliente_ref,
            intencao_id,
            dict(parametros),
        ):
            raise ChaveEmConflito(chave)
        return execucao

    def iniciar(
        self,
        chave: str,
        cliente_ref: str,
        intencao_id: str,
        parametros: Mapping[str, Any],
    ) -> Execucao:
        if chave in self._execucoes:
            raise ChaveEmConflito(chave)
        execucao = Execucao(
            chave=chave,
            cliente_ref=cliente_ref,
            intencao_id=intencao_id,
            parametros=dict(parametros),
            estado=Estado.PENDENTE,
            iniciada_em=self._relogio(),
            protocolo=f"PRT-{secrets.token_hex(4).upper()}",
        )
        self._execucoes[chave] = execucao
        return execucao

    def concluir(self, chave: str) -> Execucao:
        return self._mudar(chave, Estado.CONCLUIDA)

    def marcar_incerta(self, chave: str) -> Execucao:
        return self._mudar(chave, Estado.INCERTA)

    def incertas(self) -> list[Execucao]:
        return [e for e in self._execucoes.values() if e.estado is Estado.INCERTA]

    def contar_hoje(self, cliente_ref: str, intencao_id: str) -> int:
        """Execuções do cliente hoje, no fuso do banco. Conta também as pendentes e
        incertas: na dúvida, a execução pode ter acontecido."""
        hoje = self._relogio().astimezone(FUSO).date()
        return sum(
            1
            for e in self._execucoes.values()
            if e.cliente_ref == cliente_ref
            and e.intencao_id == intencao_id
            and e.iniciada_em.astimezone(FUSO).date() == hoje
        )

    def _mudar(self, chave: str, estado: Estado) -> Execucao:
        execucao = replace(self._execucoes[chave], estado=estado)
        self._execucoes[chave] = execucao
        return execucao
