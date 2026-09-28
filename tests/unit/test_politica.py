"""Política no fluxo agente → executor. Sem LLM."""

from dataclasses import replace

import pytest

from app.nucleo.catalogo import Canal, Catalogo
from app.nucleo.confirmacao import Confirmacoes
from app.nucleo.politica import Contexto, Motivo, Politica, Resultado

PARAMS = {"final_cartao": "1234"}


def intencao(id_: str, **campos) -> dict:
    base = {
        "id": id_,
        "descricao": id_,
        "tipo": "transacao",
        "risco": "medio",
        "nivel_autenticacao": 1,
        "canais": ["whatsapp", "app"],
        "fase": "autonomo",
        "exige_confirmacao": True,
        "ferramenta": id_,
        "texto_confirmacao": "Confirmar o cartão final {final_cartao}?",
    }
    return base | campos


CATALOGO = Catalogo.model_validate(
    {
        "versao": "t",
        "area": "cartoes",
        "intencoes": [
            intencao(
                "consultar_limite",
                tipo="consulta",
                exige_confirmacao=False,
                texto_confirmacao=None,
            ),
            intencao(
                "bloquear_cartao_temporario",
                limite_diario=3,
                texto_confirmacao="Bloquear o cartão final {final_cartao}?",
            ),
            intencao("desbloquear_cartao", nivel_autenticacao=3, canais=["app"]),
            intencao(
                "cancelar_cartao", fase="shadow", reversivel=False, nivel_autenticacao=3
            ),
        ],
    }
)

WHATSAPP_N1 = Contexto(
    cliente_ref="cli-1", sessao_id="s1", canal=Canal.WHATSAPP, nivel_autenticacao=1
)
APP_N3 = replace(WHATSAPP_N1, canal=Canal.APP, nivel_autenticacao=3)


@pytest.fixture
def politica(relogio):
    return Politica(CATALOGO, Confirmacoes(relogio=relogio))


def confirmar(politica) -> str:
    decisao = politica.avaliar("bloquear_cartao_temporario", PARAMS, WHATSAPP_N1)
    return decisao.confirmacao.id


def executar(politica, confirmacao_id, params=PARAMS, contexto=WHATSAPP_N1):
    return politica.autorizar_execucao(
        "bloquear_cartao_temporario", params, contexto, confirmacao_id
    )


def test_intencao_fora_do_catalogo_negada(politica):
    for decisao in (
        politica.avaliar("transferir_pix", PARAMS, WHATSAPP_N1),
        politica.autorizar_execucao("transferir_pix", PARAMS, WHATSAPP_N1, "x"),
    ):
        assert decisao.resultado is Resultado.NEGAR
        assert decisao.motivo is Motivo.INTENCAO_DESCONHECIDA


def test_intencao_em_shadow_negada(politica):
    decisao = politica.avaliar("cancelar_cartao", PARAMS, APP_N3)
    assert decisao.motivo is Motivo.EM_SHADOW


def test_canal_nao_permitido_negado(politica):
    no_whatsapp = replace(APP_N3, canal=Canal.WHATSAPP)
    decisao = politica.avaliar("desbloquear_cartao", PARAMS, no_whatsapp)
    assert decisao.motivo is Motivo.CANAL_NAO_PERMITIDO


def test_mesma_intencao_no_canal_permitido_pede_confirmacao(politica):
    decisao = politica.avaliar("desbloquear_cartao", PARAMS, APP_N3)
    assert decisao.resultado is Resultado.CONFIRMAR


def test_autenticacao_insuficiente_negada_com_nivel_exigido(politica):
    nivel_2 = replace(APP_N3, nivel_autenticacao=2)
    decisao = politica.avaliar("desbloquear_cartao", PARAMS, nivel_2)
    assert decisao.motivo is Motivo.AUTENTICACAO_INSUFICIENTE
    assert decisao.nivel_exigido == 3


def test_consulta_permitida_sem_confirmacao(politica):
    avaliacao = politica.avaliar("consultar_limite", {}, WHATSAPP_N1)
    execucao = politica.autorizar_execucao("consultar_limite", {}, WHATSAPP_N1)
    assert avaliacao.resultado is Resultado.PERMITIR
    assert execucao.resultado is Resultado.PERMITIR


def test_transacao_pede_confirmacao_com_texto_fixo(politica):
    decisao = politica.avaliar("bloquear_cartao_temporario", PARAMS, WHATSAPP_N1)
    assert decisao.resultado is Resultado.CONFIRMAR
    assert decisao.confirmacao.texto == "Bloquear o cartão final 1234?"


def test_transacao_confirmada_permitida(politica):
    assert executar(politica, confirmar(politica)).resultado is Resultado.PERMITIR


def test_escrita_sem_confirmacao_negada(politica):
    assert executar(politica, None).motivo is Motivo.CONFIRMACAO_AUSENTE


def test_confirmacao_forjada_negada(politica):
    assert executar(politica, "forjada").motivo is Motivo.CONFIRMACAO_INEXISTENTE


def test_parametros_trocados_negados(politica):
    decisao = executar(politica, confirmar(politica), params={"final_cartao": "9999"})
    assert decisao.motivo is Motivo.PARAMETROS_DIVERGENTES


def test_confirmacao_de_outra_sessao_negada(politica):
    outra = replace(WHATSAPP_N1, sessao_id="s2")
    decisao = executar(politica, confirmar(politica), contexto=outra)
    assert decisao.motivo is Motivo.PARAMETROS_DIVERGENTES


def test_confirmacao_reutilizada_negada(politica):
    confirmacao_id = confirmar(politica)
    executar(politica, confirmacao_id)
    decisao = executar(politica, confirmacao_id)
    assert decisao.motivo is Motivo.CONFIRMACAO_REUTILIZADA


def test_confirmacao_expirada_negada(politica, relogio):
    confirmacao_id = confirmar(politica)
    relogio.avancar(minutes=5)
    decisao = executar(politica, confirmacao_id)
    assert decisao.motivo is Motivo.CONFIRMACAO_EXPIRADA


def test_executor_refaz_a_checagem_de_autenticacao(politica):
    confirmacao_id = confirmar(politica)
    rebaixado = replace(WHATSAPP_N1, nivel_autenticacao=0)
    decisao = executar(politica, confirmacao_id, contexto=rebaixado)
    assert decisao.motivo is Motivo.AUTENTICACAO_INSUFICIENTE


@pytest.mark.parametrize(
    ("execucoes_hoje", "resultado", "motivo"),
    [(2, Resultado.CONFIRMAR, None), (3, Resultado.NEGAR, Motivo.LIMITE_DIARIO)],
)
def test_limite_diario(relogio, execucoes_hoje, resultado, motivo):
    politica = Politica(
        CATALOGO,
        Confirmacoes(relogio=relogio),
        contar_execucoes_hoje=lambda _cliente, _intencao: execucoes_hoje,
    )
    decisao = politica.avaliar("bloquear_cartao_temporario", PARAMS, WHATSAPP_N1)
    assert (decisao.resultado, decisao.motivo) == (resultado, motivo)
