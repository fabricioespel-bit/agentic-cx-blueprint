"""Textos fixos das respostas. Código preenche os valores; o LLM não redige estas mensagens.

Em produção, estes textos são configuração versionada (componente H da arquitetura).
"""

from app.nucleo.politica import Motivo

NEGACAO_PADRAO = (
    "Não consigo fazer esse pedido por aqui. Se quiser, te encaminho para um atendente."
)

NEGACOES = {
    Motivo.INTENCAO_DESCONHECIDA: NEGACAO_PADRAO,
    Motivo.EM_SHADOW: NEGACAO_PADRAO,
    Motivo.CANAL_NAO_PERMITIDO: "Esse pedido só pode ser feito no app do Banco Exemplo.",
    Motivo.AUTENTICACAO_INSUFICIENTE: (
        "Para continuar, preciso que você confirme sua identidade no app do Banco Exemplo."
    ),
    Motivo.LIMITE_DIARIO: (
        "Você atingiu o limite de pedidos desse tipo por hoje. Se quiser, te encaminho "
        "para um atendente."
    ),
}

NEGACOES_POR_INTENCAO = {
    "desbloquear_cartao": (
        "Por segurança, o desbloqueio é feito só no app do Banco Exemplo, com biometria."
    ),
}

INFORMACAO = (
    "Ainda não respondo dúvidas sobre produtos e tarifas por aqui. Posso consultar o "
    "limite ou bloquear um cartão."
)

FORA_DE_ESCOPO = (
    "Esse assunto está fora do escopo do assistente. Posso consultar o limite e "
    "bloquear o cartão."
)

PERGUNTA_CARTAO = "De qual cartão? Responda com o final do número: {opcoes}"
CARTAO_NAO_ENCONTRADO = (
    "Não encontrei esse cartão entre os seus. Se quiser, é só fazer o pedido de novo."
)
CONFIRMACAO = "{texto} Responda SIM para confirmar."
CANCELADO = "Tudo bem, não fiz nenhuma alteração."

CARTOES = "Seus cartões: {lista}."
LIMITE = "Cartão final {final}: limite total R$ {total}, disponível R$ {disponivel}."
BLOQUEADO = "Pronto: o cartão final {final} está bloqueado. Protocolo {protocolo}."
EM_VERIFICACAO = (
    "Pedi o bloqueio do cartão final {final}, mas o sistema ainda não confirmou. "
    "Acompanhe pelo protocolo {protocolo}."
)
CONFIRMACAO_INVALIDA = (
    "A confirmação não vale mais. Nada foi alterado; se quiser, é só pedir de novo."
)
FALHA = "Não consegui concluir agora e nada foi alterado. Se quiser, te encaminho para um atendente."


def negacao(intencao_id: str, motivo: str | None) -> str:
    """Retorna texto fixo de negação por intenção ou motivo."""
    if intencao_id in NEGACOES_POR_INTENCAO:
        return NEGACOES_POR_INTENCAO[intencao_id]
    return NEGACOES.get(motivo, NEGACAO_PADRAO)


def reais(valor: int) -> str:
    """Formata inteiro como BRL com ponto no lugar de vírgula."""
    return f"{valor:,}".replace(",", ".")
