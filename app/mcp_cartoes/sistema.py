"""Sistema de cartões do Banco Exemplo (mock).

Simula o sistema de origem: estado em memória e falhas de rede programáveis. Não tem
idempotência própria, como muitos legados; quem garante é o registro de execuções (D6).
Todos os dados são fictícios.
"""

from dataclasses import dataclass
from enum import StrEnum


class Situacao(StrEnum):
    ATIVO = "ativo"
    BLOQUEADO = "bloqueado"


class Falha(StrEnum):
    TIMEOUT_ANTES = "timeout_antes"  # a requisição não chegou: nada foi aplicado
    TIMEOUT_DEPOIS = "timeout_depois"  # aplicado, mas a resposta se perdeu


class TimeoutSistema(TimeoutError):
    """Sem resposta do sistema de cartões: o desfecho é desconhecido."""


@dataclass
class Cartao:
    id: str
    cliente_ref: str
    final: str
    tipo: str
    situacao: Situacao
    limite_total: int
    limite_disponivel: int


class SistemaCartoes:
    def __init__(self, cartoes: list[Cartao]):
        self._cartoes = {c.id: c for c in cartoes}
        self.proxima_falha: Falha | None = None
        self.chamadas_bloqueio = 0

    def cartoes_do_cliente(self, cliente_ref: str) -> list[Cartao]:
        return [c for c in self._cartoes.values() if c.cliente_ref == cliente_ref]

    def situacao(self, cartao_id: str) -> Situacao:
        return self._cartoes[cartao_id].situacao

    def bloquear(self, cartao_id: str) -> None:
        self.chamadas_bloqueio += 1
        falha, self.proxima_falha = self.proxima_falha, None
        if falha is Falha.TIMEOUT_ANTES:
            raise TimeoutSistema(cartao_id)
        self._cartoes[cartao_id].situacao = Situacao.BLOQUEADO
        if falha is Falha.TIMEOUT_DEPOIS:
            raise TimeoutSistema(cartao_id)


def sistema_exemplo() -> SistemaCartoes:
    return SistemaCartoes(
        [
            Cartao("c-001", "cli-1", "1234", "credito", Situacao.ATIVO, 5000, 3200),
            Cartao("c-002", "cli-1", "5678", "debito", Situacao.ATIVO, 0, 0),
            Cartao("c-003", "cli-2", "9012", "credito", Situacao.ATIVO, 8000, 8000),
        ]
    )
