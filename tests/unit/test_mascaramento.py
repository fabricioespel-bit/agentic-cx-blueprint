"""Mascaramento de dados pessoais (P4.1). Sem Google Cloud: o SDP entra como falso."""

import logging
from types import SimpleNamespace

import pytest
from google.adk.plugins.base_plugin import BasePlugin

from app.guardrails.mascaramento import (
    Achado,
    DetectorLocal,
    DetectorSDP,
    Mascarador,
)
from app.guardrails.plugin import PluginMascaramento

LOCAL = Mascarador([DetectorLocal()])


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Meu CPF é 529.982.247-25", "Meu CPF é [CPF]"),
        ("cpf 52998224725", "cpf [CPF]"),
        ("cartão 4111 1111 1111 1111", "cartão [NUMERO_DE_CARTAO]"),
        ("4111111111111111 bloqueia", "[NUMERO_DE_CARTAO] bloqueia"),
        ("e-mail maria@exemplo.com.br", "e-mail [EMAIL]"),
        ("celular (11) 98765-4321", "celular [TELEFONE]"),
    ],
)
def test_regras_locais_mascaram(texto, esperado):
    assert LOCAL.mascarar(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "bloqueia o cartão final 1234",
        "a anuidade é R$ 19,90?",
        "paguei 3000 reais em 05/10/2026",
        "CPF 123.456.789-00",  # dígito verificador inválido
        "cartão 4111 1111 1111 1112",  # falha no Luhn
    ],
)
def test_regras_locais_nao_mexem_no_que_nao_e_dado_pessoal(texto):
    assert LOCAL.mascarar(texto) == texto


class Fixo:
    """Detector falso que devolve achados prontos."""

    def __init__(self, *achados: Achado):
        self.achados = list(achados)

    def detectar(self, texto):
        return self.achados


def test_sobreposicao_fica_com_o_tipo_mais_grave():
    # Telefone e cartão no mesmo trecho: vale o cartão.
    mascarador = Mascarador(
        [Fixo(Achado(0, 10, "PHONE_NUMBER"), Achado(5, 19, "CREDIT_CARD_NUMBER"))]
    )
    assert mascarador.mascarar("4111111111111111111 ok") == "[NUMERO_DE_CARTAO] ok"


def test_detector_que_falha_nao_derruba_os_outros_nem_registra_o_texto(caplog):
    class Quebrado:
        def detectar(self, texto):
            raise TimeoutError

    with caplog.at_level(logging.WARNING):
        resultado = Mascarador([Quebrado(), DetectorLocal()]).mascarar(
            "CPF 529.982.247-25"
        )
    assert resultado == "CPF [CPF]"
    assert "Quebrado falhou" in caplog.text
    assert "529" not in caplog.text


def test_detector_sdp_usa_posicoes_em_caracteres():
    # "ã" e "ç" contam um caractere cada; em bytes UTF-8, a posição seria outra.
    texto = "Olá, é a Ana Lúcia Gonçalves"
    inicio = texto.index("Ana")
    achado = SimpleNamespace(
        info_type=SimpleNamespace(name="PERSON_NAME"),
        location=SimpleNamespace(
            codepoint_range=SimpleNamespace(start=inicio, end=len(texto))
        ),
    )
    cliente = SimpleNamespace(
        inspect_content=lambda request, timeout: SimpleNamespace(
            result=SimpleNamespace(findings=[achado])
        )
    )
    mascarador = Mascarador([DetectorSDP("projeto", cliente=cliente)])
    assert mascarador.mascarar(texto) == "Olá, é a [NOME]"


def test_plugin_sobrescreve_o_gancho_do_adk():
    # O ADK chama o gancho pelo nome: com outro nome, o mascaramento não roda e nada
    # avisa.
    assert (
        PluginMascaramento.on_user_message_callback
        is not BasePlugin.on_user_message_callback
    )
