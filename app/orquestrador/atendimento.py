"""Escalonamento ao atendimento humano (P4.3): quando encaminhar e o resumo para o atendente.

O resumo é montado por código a partir do histórico da sessão, que o plugin de auditoria
mantém no estado (um item por turno, já mascarado). Sem LLM: o atendente vai agir com
base nele, e ele só contém o que o agente de fato registrou.
"""

from typing import Any

# Desfechos que contam como falha para o encaminhamento automático.
DESFECHOS_DE_FALHA = frozenset(
    {
        "negado",
        "falha",
        "sem_fonte",
        "cartao_nao_encontrado",
        "confirmacao_invalida",
        "interrompido",
    }
)
FALHAS_SEGUIDAS = 3
HISTORICO_MAX = 10  # itens guardados no estado da sessão

MOTIVOS = {
    "pedido_do_cliente": "pedido do cliente",
    "aceite_da_oferta": "o cliente aceitou a oferta de atendimento",
    "falhas_repetidas": f"{FALHAS_SEGUIDAS} falhas seguidas",
}


def falhas_repetidas(historico: list[dict[str, Any]], desfecho_atual: str) -> bool:
    """Se o turno atual completa FALHAS_SEGUIDAS falhas seguidas na sessão."""
    if desfecho_atual not in DESFECHOS_DE_FALHA:
        return False
    anteriores = [h.get("desfecho") for h in historico[-(FALHAS_SEGUIDAS - 1) :]]
    return len(anteriores) == FALHAS_SEGUIDAS - 1 and all(
        d in DESFECHOS_DE_FALHA for d in anteriores
    )


def resumo(
    *,
    protocolo: str,
    cliente_ref: str,
    canal: str,
    nivel: int,
    motivo: str,
    historico: list[dict[str, Any]],
    ultima_mensagem: str | None,
) -> str:
    linhas = [
        f"Atendimento {protocolo}: cliente {cliente_ref}, canal {canal}, nível {nivel}.",
        f"Motivo do encaminhamento: {MOTIVOS.get(motivo, motivo)}.",
    ]
    if historico:
        linhas.append("Histórico da conversa:")
        for n, item in enumerate(historico, start=1):
            detalhe = f" ({item['motivo']})" if item.get("motivo") else ""
            intencao = item.get("intencao") or "sem intenção"
            linhas.append(f"{n}. {intencao}: {item.get('desfecho')}{detalhe}")
    if ultima_mensagem:
        linhas.append(f'Última mensagem (mascarada): "{ultima_mensagem}"')
    return "\n".join(linhas)
