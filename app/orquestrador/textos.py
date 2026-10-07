"""Textos fixos das respostas. Código preenche os valores; o LLM não redige estas mensagens.

Em produção, estes textos são configuração versionada (componente H da arquitetura).
"""

import re

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

SEM_FONTE = (
    "Não encontrei essa informação na base do Banco Exemplo. Se quiser, te encaminho "
    "para um atendente."
)
FONTES = "Fontes consultadas: {lista}."

FORA_DE_ESCOPO = (
    "Esse assunto está fora do escopo do assistente. Posso tirar dúvidas sobre cartões "
    "e tarifas, consultar o limite e bloquear o cartão."
)

PERGUNTA_CARTAO = "De qual cartão? Responda com o final do número: {opcoes}"
CARTAO_NAO_ENCONTRADO = (
    "Não encontrei esse cartão entre os seus. Se quiser, é só fazer o pedido de novo."
)
CONFIRMACAO = "{texto} Responda SIM para confirmar."
NUMERO_DE_CARTAO = (
    "Por segurança, não envie o número completo do cartão: ele foi descartado. Para "
    "falar de um cartão, use só os 4 últimos dígitos."
)
CANCELADO = "Tudo bem, não fiz nenhuma alteração."

CARTOES = "Seus cartões: {lista}."
LIMITE = "Cartão final {final}: limite total R$ {total}, disponível R$ {disponivel}."
BLOQUEADO = "Pronto: o cartão final {final} está bloqueado. Protocolo {protocolo}."
EM_VERIFICACAO = (
    "Pedi o bloqueio do cartão final {final}, mas o sistema ainda não confirmou. "
    "Acompanhe pelo protocolo {protocolo}."
)
JA_BLOQUEADO = (
    "O cartão final {final} já está bloqueado; não fiz nenhuma alteração. "
    "O desbloqueio é feito só no app do Banco Exemplo."
)
CONFIRMACAO_INVALIDA = (
    "A confirmação não vale mais. Nada foi alterado; se quiser, é só pedir de novo."
)
FALHA = "Não consegui concluir agora e nada foi alterado. Se quiser, te encaminho para um atendente."


# Escalonamento (P4.3). A oferta está em NEGACAO_PADRAO, LIMITE_DIARIO, SEM_FONTE e FALHA.
OFERTA_ATENDENTE = "te encaminho para um atendente"
ENCAMINHADO = (
    "Certo, vou te encaminhar para um atendente. Ele vai receber o resumo do que "
    "conversamos, sem você precisar repetir. Protocolo {protocolo}."
)
ENCAMINHADO_FALHAS = (
    "Não estou conseguindo resolver por aqui. Vou te encaminhar para um atendente, que "
    "vai receber o resumo do que conversamos. Protocolo {protocolo}."
)
JA_ENCAMINHADO = (
    "Seu atendimento já foi encaminhado (protocolo {protocolo}). Um atendente vai "
    "continuar a conversa por aqui."
)


# Mensagem barrada pelo filtro de entrada (P4.4). Sem oferta de atendente, de propósito:
# com ela, três tentativas de ataque seguidas levariam o atacante a um humano.
MENSAGEM_BARRADA = (
    "Não consigo seguir com essa mensagem. Se precisar de algo sobre seus cartões, é só "
    "me dizer."
)


def negacao(intencao_id: str, motivo: str | None) -> str:
    """Retorna texto fixo de negação por intenção ou motivo."""
    if intencao_id in NEGACOES_POR_INTENCAO:
        return NEGACOES_POR_INTENCAO[intencao_id]
    return NEGACOES.get(motivo, NEGACAO_PADRAO)


def reais(valor: int) -> str:
    """Formata inteiro como BRL com ponto no lugar de vírgula."""
    return f"{valor:,}".replace(",", ".")


def _modelo(texto: str) -> re.Pattern:
    """Texto fixo com campos ({final}, {texto}...) vira expressão regular."""
    partes = re.split(r"\{[^}]*\}", texto)
    return re.compile(".*".join(re.escape(p) for p in partes), flags=re.DOTALL)


RODAPE_FONTES = FONTES.split("{")[0]
# Desfecho de um turno, reconhecido pelo texto fixo que o cliente recebeu.
DESFECHOS = [
    (_modelo(NUMERO_DE_CARTAO), "aviso_cartao"),
    (_modelo(SEM_FONTE), "sem_fonte"),
    (_modelo(FORA_DE_ESCOPO), "fora_de_escopo"),
    (_modelo(PERGUNTA_CARTAO), "pergunta_cartao"),
    (_modelo(CONFIRMACAO), "confirmacao_pedida"),
    (_modelo(CANCELADO), "cancelado"),
    (_modelo(BLOQUEADO), "executado"),
    (_modelo(EM_VERIFICACAO), "execucao_incerta"),
    (_modelo(JA_BLOQUEADO), "ja_bloqueado"),
    (_modelo(CONFIRMACAO_INVALIDA), "confirmacao_invalida"),
    (_modelo(CARTAO_NAO_ENCONTRADO), "cartao_nao_encontrado"),
    (_modelo(LIMITE), "consulta"),
    (_modelo(CARTOES), "consulta"),
    (_modelo(FALHA), "falha"),
    (_modelo(ENCAMINHADO), "encaminhado"),
    (_modelo(ENCAMINHADO_FALHAS), "encaminhado"),
    (_modelo(JA_ENCAMINHADO), "ja_encaminhado"),
    (_modelo(MENSAGEM_BARRADA), "barrado"),
    *[
        (_modelo(t), "negado")
        for t in (NEGACAO_PADRAO, *NEGACOES.values(), *NEGACOES_POR_INTENCAO.values())
    ],
]


def desfecho(resposta: str) -> str:
    # Turno sem resposta: erro no grafo ou cliente que desistiu de esperar.
    if not resposta.strip():
        return "interrompido"
    if RODAPE_FONTES in resposta:
        return "respondido"
    for modelo, nome in DESFECHOS:
        if modelo.fullmatch(resposta):
            return nome
    return "outro"
