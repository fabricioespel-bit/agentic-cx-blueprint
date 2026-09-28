"""Catálogo de intenções e piso de invariantes. Sem LLM."""

import pytest
from pydantic import ValidationError

from app.nucleo.catalogo import (
    Catalogo,
    Fase,
    Intencao,
    IntencaoDesconhecida,
    ViolacaoDeInvariante,
    carregar_catalogo,
    validar_publicacao,
)


def transacao(**campos) -> dict:
    base = {
        "id": "bloquear_cartao_temporario",
        "descricao": "Bloqueio temporário",
        "tipo": "transacao",
        "risco": "medio",
        "nivel_autenticacao": 1,
        "canais": ["whatsapp"],
        "fase": "assistido",
        "reversivel": True,
        "exige_confirmacao": True,
        "ferramenta": "bloquear_cartao",
    }
    return base | campos


def catalogo(*intencoes: dict) -> Catalogo:
    return Catalogo.model_validate(
        {"versao": "t", "area": "cartoes", "intencoes": list(intencoes)}
    )


def test_catalogo_do_repositorio_carrega():
    cat = carregar_catalogo()
    assert cat.area == "cartoes"
    assert cat.obter("bloquear_cartao_temporario").escrita


def test_intencao_fora_do_catalogo_negada():
    with pytest.raises(IntencaoDesconhecida):
        carregar_catalogo().obter("transferir_pix")


def test_desbloqueio_exige_nivel_3_e_so_app():
    desbloqueio = carregar_catalogo().obter("desbloquear_cartao")
    assert desbloqueio.nivel_autenticacao == 3
    assert {c.value for c in desbloqueio.canais} == {"app"}


def test_transacao_valida_carrega():
    assert Intencao.model_validate(transacao()).exige_confirmacao


def test_transacao_sem_confirmacao_viola_piso():
    with pytest.raises(ValidationError, match="sem confirmação"):
        Intencao.model_validate(transacao(exige_confirmacao=False))


def test_irreversivel_abaixo_do_nivel_3_viola_piso():
    with pytest.raises(ValidationError, match="irreversível"):
        Intencao.model_validate(transacao(reversivel=False, nivel_autenticacao=2))


def test_irreversivel_no_nivel_3_aceito():
    assert Intencao.model_validate(transacao(reversivel=False, nivel_autenticacao=3))


@pytest.mark.parametrize("tipo", ["consulta", "transacao"])
def test_dado_do_cliente_com_nivel_0_viola_piso(tipo):
    with pytest.raises(ValidationError, match="nível 0"):
        Intencao.model_validate(transacao(tipo=tipo, nivel_autenticacao=0))


def test_consulta_sem_ferramenta_viola_piso():
    with pytest.raises(ValidationError, match="sem ferramenta"):
        Intencao.model_validate(transacao(tipo="consulta", ferramenta=None))


def test_campo_desconhecido_rejeitado():
    with pytest.raises(ValidationError):
        Intencao.model_validate(transacao(pular_confirmacao=True))


def test_sem_canal_rejeitado():
    with pytest.raises(ValidationError):
        Intencao.model_validate(transacao(canais=[]))


def test_ids_repetidos_rejeitados():
    with pytest.raises(ValidationError, match="repetidas"):
        catalogo(transacao(), transacao())


def test_catalogo_imutavel():
    cat = carregar_catalogo()
    with pytest.raises(ValidationError):
        cat.obter("listar_cartoes").nivel_autenticacao = 0


def test_intencao_nova_fora_de_shadow_barrada_na_publicacao():
    anterior = catalogo(transacao())
    novo = catalogo(transacao(), transacao(id="cancelar_cartao", fase="autonomo"))
    with pytest.raises(ViolacaoDeInvariante, match="cancelar_cartao"):
        validar_publicacao(novo, anterior)


def test_intencao_nova_em_shadow_e_existente_promovida_aceitas():
    anterior = catalogo(transacao(fase="shadow"))
    novo = catalogo(
        transacao(fase=Fase.AUTONOMO), transacao(id="cancelar_cartao", fase="shadow")
    )
    validar_publicacao(novo, anterior)


def test_primeira_publicacao_exige_shadow_em_tudo():
    with pytest.raises(ViolacaoDeInvariante):
        validar_publicacao(catalogo(transacao()), None)
