"""Servidor MCP de cartões: política no executor, idempotência e reconciliação.

Identidade e confirmação chegam no ``_meta`` da requisição, preenchido pelo código do
agente e do gateway. Não fazem parte do schema das ferramentas: o LLM não as vê nem as
escolhe. Toda chamada passa pela política (vale a do executor); a escrita passa também
pelo registro de execuções.

Mock: o token de sessão vem no ``_meta``; em produção, no header HTTP, verificado pelo
servidor. Anotações de leitura/escrita e outbox de eventos são propostos.
"""

from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from app.mcp_cartoes.sistema import Cartao, SistemaCartoes, Situacao, TimeoutSistema
from app.nucleo.execucoes import ChaveEmConflito, Estado, Execucao, RegistroExecucoes
from app.nucleo.politica import Contexto, Politica, Resultado
from app.nucleo.sessao import CofreSessao, SessaoInvalida

META_SESSAO = "io.bancoexemplo/sessao"
META_CONFIRMACAO = "io.bancoexemplo/confirmacao"

BLOQUEIO = "bloquear_cartao_temporario"


class Recusa(Exception):
    """Pedido recusado; a mensagem é o motivo."""


class ServicoCartoes:
    """Regras do executor, sem dependência do protocolo (testável direto)."""

    def __init__(
        self, politica: Politica, sistema: SistemaCartoes, registro: RegistroExecucoes
    ):
        self._politica = politica
        self._sistema = sistema
        self._registro = registro

    def listar_cartoes(self, contexto: Contexto) -> dict[str, Any]:
        self._autorizar("listar_cartoes", {}, contexto)
        cartoes = self._sistema.cartoes_do_cliente(contexto.cliente_ref)
        return {
            "cartoes": [
                {"final": c.final, "tipo": c.tipo, "situacao": c.situacao.value}
                for c in cartoes
            ]
        }

    def consultar_limite(self, contexto: Contexto, final_cartao: str) -> dict[str, Any]:
        self._autorizar("consultar_limite", {"final_cartao": final_cartao}, contexto)
        cartao = self._cartao(contexto.cliente_ref, final_cartao)
        return {
            "final": cartao.final,
            "limite_total": cartao.limite_total,
            "limite_disponivel": cartao.limite_disponivel,
        }

    def bloquear_cartao(
        self, contexto: Contexto, final_cartao: str, confirmacao_id: str | None
    ) -> dict[str, Any]:
        parametros = {"final_cartao": final_cartao}
        if confirmacao_id is not None:
            try:
                anterior = self._registro.obter(
                    confirmacao_id, contexto.cliente_ref, BLOQUEIO, parametros
                )
            except ChaveEmConflito as erro:
                raise Recusa("chave_em_conflito") from erro
            if anterior is not None:
                return self._retomar(anterior)
        self._autorizar(BLOQUEIO, parametros, contexto, confirmacao_id)
        cartao = self._cartao(contexto.cliente_ref, final_cartao)
        execucao = self._registro.iniciar(
            confirmacao_id, contexto.cliente_ref, BLOQUEIO, parametros
        )
        return self._executar(execucao, cartao)

    def reconciliar(self) -> list[dict[str, Any]]:
        """Revisita execuções incertas; conclui as que o sistema confirma."""
        resolvidas = []
        for execucao in self._registro.incertas():
            cartao = self._cartao_da_execucao(execucao)
            if self._sistema.situacao(cartao.id) is Situacao.BLOQUEADO:
                resolvidas.append(_resposta(self._registro.concluir(execucao.chave)))
        return resolvidas

    def _retomar(self, execucao: Execucao) -> dict[str, Any]:
        # Mesma chave de novo: concluída devolve o mesmo resultado sem executar; pendente
        # ou incerta consulta o estado antes de reexecutar.
        if execucao.estado is Estado.CONCLUIDA:
            return _resposta(execucao)
        cartao = self._cartao_da_execucao(execucao)
        if self._sistema.situacao(cartao.id) is Situacao.BLOQUEADO:
            return _resposta(self._registro.concluir(execucao.chave))
        return self._executar(execucao, cartao)

    def _executar(self, execucao: Execucao, cartao: Cartao) -> dict[str, Any]:
        try:
            self._sistema.bloquear(cartao.id)
        except TimeoutSistema:
            if self._sistema.situacao(cartao.id) is Situacao.BLOQUEADO:
                return _resposta(self._registro.concluir(execucao.chave))
            return _resposta(self._registro.marcar_incerta(execucao.chave))
        return _resposta(self._registro.concluir(execucao.chave))

    def _autorizar(
        self,
        intencao_id: str,
        parametros: dict[str, Any],
        contexto: Contexto,
        confirmacao_id: str | None = None,
    ) -> None:
        decisao = self._politica.autorizar_execucao(
            intencao_id, parametros, contexto, confirmacao_id
        )
        if decisao.resultado is not Resultado.PERMITIR:
            raise Recusa(decisao.motivo)

    def _cartao(self, cliente_ref: str, final_cartao: str) -> Cartao:
        for cartao in self._sistema.cartoes_do_cliente(cliente_ref):
            if cartao.final == final_cartao:
                return cartao
        raise Recusa("cartao_nao_encontrado")

    def _cartao_da_execucao(self, execucao: Execucao) -> Cartao:
        return self._cartao(execucao.cliente_ref, execucao.parametros["final_cartao"])


def _resposta(execucao: Execucao) -> dict[str, Any]:
    return {
        "estado": execucao.estado.value,
        "final": execucao.parametros["final_cartao"],
        "protocolo": execucao.protocolo,
    }


def _meta(ctx: Context, chave: str) -> Any:
    meta = ctx.request_context.meta
    return (meta.model_extra or {}).get(chave) if meta else None


def _chamar(funcao: Callable[..., dict[str, Any]], *args: Any) -> dict[str, Any]:
    try:
        return funcao(*args)
    except Recusa as recusa:
        raise ToolError(str(recusa)) from recusa


def criar_servidor(servico: ServicoCartoes, cofre: CofreSessao) -> FastMCP:
    mcp = FastMCP("cartoes-banco-exemplo")

    def contexto(ctx: Context) -> Contexto:
        try:
            return cofre.resolver(_meta(ctx, META_SESSAO))
        except SessaoInvalida as erro:
            raise ToolError("sessao_invalida") from erro

    @mcp.tool()
    def listar_cartoes(ctx: Context) -> dict[str, Any]:
        """Lista os cartões do cliente: final, tipo e situação."""
        return _chamar(servico.listar_cartoes, contexto(ctx))

    @mcp.tool()
    def consultar_limite(final_cartao: str, ctx: Context) -> dict[str, Any]:
        """Informa o limite total e o disponível de um cartão do cliente."""
        return _chamar(servico.consultar_limite, contexto(ctx), final_cartao)

    @mcp.tool()
    def bloquear_cartao(final_cartao: str, ctx: Context) -> dict[str, Any]:
        """Bloqueia temporariamente um cartão do cliente. Exige confirmação."""
        return _chamar(
            servico.bloquear_cartao,
            contexto(ctx),
            final_cartao,
            _meta(ctx, META_CONFIRMACAO),
        )

    return mcp
