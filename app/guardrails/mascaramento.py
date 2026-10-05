"""Mascaramento de dados pessoais antes do LLM (P4.1; decisões D2 e N3).

Toda mensagem do cliente passa por aqui antes de ser gravada na sessão e de chegar ao
classificador. Dados pessoais viram marcadores legíveis ([CPF], [EMAIL]...); número
completo de cartão vira [NUMERO_DE_CARTAO], e o agente pede para não enviá-lo (fora do
escopo PCI). Os 4 últimos dígitos ("final 1234") passam: o bloqueio precisa deles.

Duas camadas que rodam juntas: o Sensitive Data Protection (SDP) do Google, no endpoint
regional (o dado real não sai da região), e regras locais com dígito verificador para
CPF e cartão. Se o SDP falhar, as regras locais seguem e a falha é registrada, sem o
texto.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

MARCADORES = {
    "CREDIT_CARD_NUMBER": "[NUMERO_DE_CARTAO]",
    "BRAZIL_CPF_NUMBER": "[CPF]",
    "EMAIL_ADDRESS": "[EMAIL]",
    "PHONE_NUMBER": "[TELEFONE]",
    "STREET_ADDRESS": "[ENDERECO]",
    "PERSON_NAME": "[NOME]",
}
# Em trechos sobrepostos vale o tipo mais grave: a ordem de MARCADORES.
PRIORIDADE = {tipo: i for i, tipo in enumerate(MARCADORES)}
CARTAO = MARCADORES["CREDIT_CARD_NUMBER"]


@dataclass(frozen=True)
class Achado:
    inicio: int
    fim: int
    tipo: str  # uma chave de MARCADORES


class Detector(Protocol):
    def detectar(self, texto: str) -> list[Achado]: ...


class Mascarador:
    """Junta os achados de todos os detectores e troca cada trecho pelo marcador."""

    def __init__(self, detectores: list[Detector]):
        self._detectores = detectores

    def mascarar(self, texto: str) -> str:
        achados: list[Achado] = []
        for detector in self._detectores:
            try:
                achados += detector.detectar(texto)
            except Exception:
                # Nunca registrar o texto: ele ainda tem os dados pessoais.
                logger.warning("detector %s falhou", type(detector).__name__)
        return _aplicar(texto, achados)


def _aplicar(texto: str, achados: list[Achado]) -> str:
    validos = [a for a in achados if a.tipo in MARCADORES and a.inicio < a.fim]
    trechos: list[list[Any]] = []  # [inicio, fim, tipo], já unindo sobreposições
    for achado in sorted(validos, key=lambda a: a.inicio):
        if trechos and achado.inicio < trechos[-1][1]:
            atual = trechos[-1]
            atual[1] = max(atual[1], achado.fim)
            if PRIORIDADE[achado.tipo] < PRIORIDADE[atual[2]]:
                atual[2] = achado.tipo
        else:
            trechos.append([achado.inicio, achado.fim, achado.tipo])
    for inicio, fim, tipo in reversed(trechos):
        texto = texto[:inicio] + MARCADORES[tipo] + texto[fim:]
    return texto


class DetectorLocal:
    """Regras locais. CPF e cartão só contam com dígito verificador válido."""

    CPF = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
    CARTAO = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
    EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
    TELEFONE = re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-\d{4}\b")

    def detectar(self, texto: str) -> list[Achado]:
        achados = []
        for regra, tipo, valido in (
            (self.CPF, "BRAZIL_CPF_NUMBER", _cpf_valido),
            (self.CARTAO, "CREDIT_CARD_NUMBER", _luhn_valido),
            (self.EMAIL, "EMAIL_ADDRESS", None),
            (self.TELEFONE, "PHONE_NUMBER", None),
        ):
            for m in regra.finditer(texto):
                if valido is None or valido(re.sub(r"\D", "", m.group())):
                    achados.append(Achado(m.start(), m.end(), tipo))
        return achados


def _cpf_valido(digitos: str) -> bool:
    if len(digitos) != 11 or len(set(digitos)) == 1:
        return False
    for tamanho in (9, 10):
        soma = sum(int(d) * (tamanho + 1 - i) for i, d in enumerate(digitos[:tamanho]))
        if (soma * 10 % 11) % 10 != int(digitos[tamanho]):
            return False
    return True


def _luhn_valido(digitos: str) -> bool:
    if not 13 <= len(digitos) <= 19:
        return False
    soma = 0
    for i, d in enumerate(reversed(digitos)):
        n = int(d) * (2 if i % 2 else 1)
        soma += n - 9 if n > 9 else n
    return soma % 10 == 0


class DetectorSDP:
    """Sensitive Data Protection no endpoint regional: o texto real fica na região."""

    TEMPO_LIMITE = 3.0  # segundos; depois disso, valem só as regras locais

    def __init__(self, projeto: str, regiao: str = "southamerica-east1", cliente=None):
        # Cliente criado na primeira chamada: importar o agente (testes, CI) não exige
        # credenciais do Google Cloud.
        self._cliente = cliente
        self._endpoint = f"dlp.{regiao}.rep.googleapis.com"
        self._pedido = {
            "parent": f"projects/{projeto}/locations/{regiao}",
            "inspect_config": {
                "info_types": [{"name": tipo} for tipo in MARCADORES],
                # "Possível": cartão sem espaços e nome completo só aparecem nesse nível.
                "min_likelihood": "POSSIBLE",
            },
        }

    def detectar(self, texto: str) -> list[Achado]:
        if self._cliente is None:
            from google.api_core.client_options import ClientOptions
            from google.cloud import dlp_v2

            self._cliente = dlp_v2.DlpServiceClient(
                client_options=ClientOptions(api_endpoint=self._endpoint)
            )
        resposta = self._cliente.inspect_content(
            request={**self._pedido, "item": {"value": texto}},
            timeout=self.TEMPO_LIMITE,
        )
        # codepoint_range conta caracteres, como os índices de str em Python.
        return [
            Achado(
                a.location.codepoint_range.start,
                a.location.codepoint_range.end,
                a.info_type.name,
            )
            for a in resposta.result.findings
        ]
