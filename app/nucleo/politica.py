"""Política: decide se uma intenção pode seguir e com quais exigências (N1, D3, D4).

É consultada duas vezes: pelo agente, para conduzir a conversa (``avaliar``), e pelo
executor (servidor MCP), que barra na execução (``autorizar_execucao``). Vale a do executor.
Identidade, canal e nível de autenticação vêm do contexto autenticado da requisição, nunca
de parâmetro escolhido pelo LLM.

Limitação do protótipo: a fase "assistido" ainda é tratada como "autonomo".
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.nucleo.catalogo import Canal, Catalogo, Fase, Intencao, IntencaoDesconhecida
from app.nucleo.confirmacao import Confirmacao, ConfirmacaoInvalida, Confirmacoes

ContadorExecucoes = Callable[[str, str], int]
"""(cliente_ref, intencao_id) -> execuções bem-sucedidas hoje."""


def _sem_execucoes(cliente_ref: str, intencao_id: str) -> int:
    return 0


class Resultado(StrEnum):
    PERMITIR = "permitir"
    CONFIRMAR = "confirmar"
    NEGAR = "negar"


class Motivo(StrEnum):
    INTENCAO_DESCONHECIDA = "intencao_desconhecida"
    EM_SHADOW = "em_shadow"
    CANAL_NAO_PERMITIDO = "canal_nao_permitido"
    AUTENTICACAO_INSUFICIENTE = "autenticacao_insuficiente"
    LIMITE_DIARIO = "limite_diario"
    CONFIRMACAO_AUSENTE = "confirmacao_ausente"
    # Mesmos valores de FalhaConfirmacao.
    CONFIRMACAO_INEXISTENTE = "confirmacao_inexistente"
    CONFIRMACAO_REUTILIZADA = "confirmacao_reutilizada"
    CONFIRMACAO_EXPIRADA = "confirmacao_expirada"
    PARAMETROS_DIVERGENTES = "parametros_divergentes"


@dataclass(frozen=True)
class Contexto:
    """Preenchido pelo gateway a partir da sessão autenticada."""

    cliente_ref: str  # pseudônimo do cliente
    sessao_id: str
    canal: Canal
    nivel_autenticacao: int


@dataclass(frozen=True)
class Decisao:
    resultado: Resultado
    motivo: Motivo | None = None
    confirmacao: Confirmacao | None = None
    nivel_exigido: int | None = None  # preenchido na negação por autenticação


def _negar(motivo: Motivo, nivel_exigido: int | None = None) -> Decisao:
    return Decisao(Resultado.NEGAR, motivo, nivel_exigido=nivel_exigido)


class Politica:
    def __init__(
        self,
        catalogo: Catalogo,
        confirmacoes: Confirmacoes,
        contar_execucoes_hoje: ContadorExecucoes = _sem_execucoes,
    ):
        self._catalogo = catalogo
        self._confirmacoes = confirmacoes
        self._contar = contar_execucoes_hoje

    def avaliar(
        self, intencao_id: str, parametros: Mapping[str, Any], contexto: Contexto
    ) -> Decisao:
        """Pré-check do agente. Para transação, emite a confirmação a mostrar ao cliente."""
        intencao = self._verificar(intencao_id, contexto)
        if isinstance(intencao, Decisao):
            return intencao
        if not intencao.escrita:
            return Decisao(Resultado.PERMITIR)
        confirmacao = self._confirmacoes.emitir(
            intencao, contexto.sessao_id, parametros
        )
        return Decisao(Resultado.CONFIRMAR, confirmacao=confirmacao)

    def autorizar_execucao(
        self,
        intencao_id: str,
        parametros: Mapping[str, Any],
        contexto: Contexto,
        confirmacao_id: str | None = None,
    ) -> Decisao:
        """Checagem no executor: refaz tudo e, para escrita, consome a confirmação."""
        intencao = self._verificar(intencao_id, contexto)
        if isinstance(intencao, Decisao):
            return intencao
        if not intencao.escrita:
            return Decisao(Resultado.PERMITIR)
        if confirmacao_id is None:
            return _negar(Motivo.CONFIRMACAO_AUSENTE)
        try:
            self._confirmacoes.consumir(
                confirmacao_id, contexto.sessao_id, intencao.id, parametros
            )
        except ConfirmacaoInvalida as erro:
            return _negar(Motivo(erro.falha.value))
        return Decisao(Resultado.PERMITIR)

    def _verificar(self, intencao_id: str, contexto: Contexto) -> Intencao | Decisao:
        try:
            intencao = self._catalogo.obter(intencao_id)
        except IntencaoDesconhecida:
            return _negar(Motivo.INTENCAO_DESCONHECIDA)
        if intencao.fase is Fase.SHADOW:
            return _negar(Motivo.EM_SHADOW)
        if contexto.canal not in intencao.canais:
            return _negar(Motivo.CANAL_NAO_PERMITIDO)
        if contexto.nivel_autenticacao < intencao.nivel_autenticacao:
            return _negar(Motivo.AUTENTICACAO_INSUFICIENTE, intencao.nivel_autenticacao)
        if (
            intencao.limite_diario is not None
            and self._contar(contexto.cliente_ref, intencao.id)
            >= intencao.limite_diario
        ):
            return _negar(Motivo.LIMITE_DIARIO)
        return intencao
