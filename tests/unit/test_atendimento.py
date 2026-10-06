"""Escalonamento (P4.3): falhas seguidas e resumo para o atendente. Sem LLM."""

from app.orquestrador.atendimento import falhas_repetidas, resumo

NEGADO = {"intencao": "transferir_pix", "desfecho": "negado", "motivo": "x"}
OK = {"intencao": "consultar_limite", "desfecho": "consulta", "motivo": None}


def test_tres_falhas_seguidas():
    assert falhas_repetidas([NEGADO, NEGADO], "negado")
    assert not falhas_repetidas([NEGADO], "negado")  # só duas
    assert not falhas_repetidas([NEGADO, OK], "negado")  # não seguidas
    assert not falhas_repetidas([NEGADO, NEGADO], "consulta")  # o turno atual deu certo


def test_fora_de_escopo_nao_conta_como_falha():
    fora = {"intencao": "fora_de_escopo", "desfecho": "fora_de_escopo", "motivo": None}
    assert not falhas_repetidas([fora, fora], "fora_de_escopo")


def test_resumo_para_o_atendente():
    texto = resumo(
        protocolo="ATD-1",
        cliente_ref="cli-1",
        canal="whatsapp",
        nivel=1,
        motivo="aceite_da_oferta",
        historico=[OK, NEGADO],
        ultima_mensagem="meu CPF é [CPF]",
    )
    assert texto == (
        "Atendimento ATD-1: cliente cli-1, canal whatsapp, nível 1.\n"
        "Motivo do encaminhamento: o cliente aceitou a oferta de atendimento.\n"
        "Histórico da conversa:\n"
        "1. consultar_limite: consulta\n"
        "2. transferir_pix: negado (x)\n"
        'Última mensagem (mascarada): "meu CPF é [CPF]"'
    )
