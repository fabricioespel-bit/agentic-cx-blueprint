"""Cofre de sessão (decisão N2): token opaco → contexto autenticado.

O gateway autentica o cliente e guarda o contexto no cofre; o agente carrega só o token
opaco, e o servidor MCP troca o token pelo contexto. O LLM nunca vê nem escolhe identidade.

Mock: dicionário em memória, sem expiração nem criptografia; em produção, armazenamento
dedicado com acesso restrito ao gateway e ao servidor MCP.
"""

import secrets

from app.nucleo.politica import Contexto


class SessaoInvalida(LookupError):
    """Token ausente, desconhecido ou encerrado."""


class CofreSessao:
    def __init__(self) -> None:
        self._sessoes: dict[str, Contexto] = {}

    def abrir(self, contexto: Contexto) -> str:
        token = secrets.token_urlsafe(24)
        self._sessoes[token] = contexto
        return token

    def resolver(self, token: str | None) -> Contexto:
        if token is None or token not in self._sessoes:
            raise SessaoInvalida("sessão inválida")
        return self._sessoes[token]

    def encerrar(self, token: str) -> None:
        self._sessoes.pop(token, None)
