"""Filtro de entrada do LLM (P4.4; decisão N3): Model Armor sobre o texto já mascarado.

Uma checagem por turno, só quando a mensagem vai para um LLM: injeção de prompt e
jailbreak, conteúdo impróprio (ódio, assédio, sexual, perigoso) e URLs maliciosas. O
Model Armor fica em us-central1 (não há em southamerica-east1); recebe o mesmo texto
mascarado que já vai ao Gemini global, então a exposição não aumenta.

É camada de redução, não a garantia: o que impede uma ação indevida são o catálogo, a
política e a confirmação. Por isso, se o Model Armor falhar, a mensagem segue e a
falha fica registrada.
"""

import logging
from dataclasses import dataclass, field
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Avaliacao:
    barrado: bool
    filtros: list[str] = field(default_factory=list)  # o que barrou
    indisponivel: bool = False


class Filtro(Protocol):
    def avaliar(self, texto: str) -> Avaliacao: ...


class SemFiltro:
    """Sem projeto configurado (testes unitários): libera tudo."""

    def avaliar(self, texto: str) -> Avaliacao:
        return Avaliacao(barrado=False)


class FiltroModelArmor:
    TEMPO_LIMITE = 3.0  # segundos; depois disso, a mensagem segue sem o filtro

    def __init__(
        self,
        projeto: str,
        regiao: str = "us-central1",
        template: str = "atendimento-entrada",
        cliente=None,
    ):
        # Cliente criado na primeira chamada e reaproveitado: importar o agente não exige
        # credenciais, e a conexão (cerca de 1,7 s na sondagem) é paga uma vez só.
        self._cliente = cliente
        self._endpoint = f"modelarmor.{regiao}.rep.googleapis.com"
        self._template = f"projects/{projeto}/locations/{regiao}/templates/{template}"

    def avaliar(self, texto: str) -> Avaliacao:
        try:
            resultado = self._analisar(texto)
        except Exception:
            # Nunca registrar o texto.
            logger.warning("model armor indisponível; a mensagem segue sem o filtro")
            return Avaliacao(barrado=False, indisponivel=True)
        if resultado.filter_match_state.name != "MATCH_FOUND":
            return Avaliacao(barrado=False)
        return Avaliacao(barrado=True, filtros=_filtros(resultado))

    def _analisar(self, texto: str):
        from google.cloud import modelarmor_v1

        if self._cliente is None:
            self._cliente = modelarmor_v1.ModelArmorClient(
                client_options={"api_endpoint": self._endpoint}
            )
        resposta = self._cliente.sanitize_user_prompt(
            request=modelarmor_v1.SanitizeUserPromptRequest(
                name=self._template,
                user_prompt_data=modelarmor_v1.DataItem(text=texto),
            ),
            timeout=self.TEMPO_LIMITE,
        )
        return resposta.sanitization_result


def _filtros(resultado) -> list[str]:
    """Nomes dos filtros que barraram, sem o texto."""
    nomes = []
    for nome, filtro in resultado.filter_results.items():
        if nome == "pi_and_jailbreak":
            if filtro.pi_and_jailbreak_filter_result.match_state.name == "MATCH_FOUND":
                nomes.append("injecao")
        elif nome == "rai":
            tipos = filtro.rai_filter_result.rai_filter_type_results.items()
            nomes += [
                f"conteudo:{tipo}"
                for tipo, r in tipos
                if r.match_state.name == "MATCH_FOUND"
            ]
        elif nome == "malicious_uris":
            if filtro.malicious_uri_filter_result.match_state.name == "MATCH_FOUND":
                nomes.append("url_maliciosa")
    return sorted(nomes)
