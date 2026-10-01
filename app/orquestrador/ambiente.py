"""Liga as peças do núcleo para o protótipo.

Tudo aqui é mock e roda no mesmo processo: sistema de cartões, cofre de sessão, registro
de execuções e o servidor MCP (protocolo real, conectado em memória). Em produção, o
servidor MCP roda em serviço próprio e a sessão é aberta pelo gateway de canal.
"""

import json
from dataclasses import dataclass
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session as conectar

from app.conhecimento.busca import Buscador, BuscadorLocal
from app.conhecimento.corpus import Corpus, carregar_corpus
from app.mcp_cartoes.servidor import (
    META_CONFIRMACAO,
    META_SESSAO,
    ServicoCartoes,
    criar_servidor,
)
from app.mcp_cartoes.sistema import SistemaCartoes, sistema_exemplo
from app.nucleo.catalogo import Canal, Catalogo, carregar_catalogo
from app.nucleo.confirmacao import Confirmacoes, Relogio, agora_utc
from app.nucleo.execucoes import RegistroExecucoes
from app.nucleo.politica import Contexto, Politica
from app.nucleo.sessao import CofreSessao

CLIENTE_DEMO = "cli-1"
# Vigência de documentos é data de calendário no Brasil, não em UTC.
FUSO = ZoneInfo("America/Sao_Paulo")


@dataclass(frozen=True)
class RespostaMcp:
    dados: dict[str, Any] | None
    motivo: str | None  # preenchido quando o servidor recusa

    @property
    def ok(self) -> bool:
        return self.motivo is None


@dataclass
class Ambiente:
    catalogo: Catalogo
    politica: Politica
    cofre: CofreSessao
    servidor: FastMCP
    sistema: SistemaCartoes  # exposto para simular falhas nos testes
    corpus: Corpus
    buscador: Buscador
    relogio: Relogio

    def hoje(self) -> date:
        return self.relogio().astimezone(FUSO).date()

    def abrir_sessao_demo(self, sessao_id: str) -> str:
        """Faz o papel do gateway: cliente de demonstração, WhatsApp, nível 1."""
        contexto = Contexto(
            cliente_ref=CLIENTE_DEMO,
            sessao_id=sessao_id,
            canal=Canal.WHATSAPP,
            nivel_autenticacao=1,
        )
        return self.cofre.abrir(contexto)

    async def chamar(
        self,
        ferramenta: str,
        argumentos: dict[str, Any],
        token: str,
        confirmacao: str | None = None,
    ) -> RespostaMcp:
        meta = {META_SESSAO: token}
        if confirmacao is not None:
            meta[META_CONFIRMACAO] = confirmacao
        async with conectar(self.servidor) as sessao:
            resultado = await sessao.call_tool(ferramenta, argumentos, meta=meta)
        texto = resultado.content[0].text
        if resultado.isError:
            return RespostaMcp(None, texto.rsplit(": ", 1)[-1])
        return RespostaMcp(json.loads(texto), None)


def criar_ambiente(relogio: Relogio = agora_utc) -> Ambiente:
    catalogo = carregar_catalogo()
    registro = RegistroExecucoes(relogio=relogio)
    politica = Politica(
        catalogo,
        Confirmacoes(relogio=relogio),
        contar_execucoes_hoje=registro.contar_hoje,
    )
    cofre = CofreSessao()
    sistema = sistema_exemplo()
    servico = ServicoCartoes(politica, sistema, registro)
    corpus = carregar_corpus()
    return Ambiente(
        catalogo,
        politica,
        cofre,
        criar_servidor(servico, cofre),
        sistema,
        corpus,
        BuscadorLocal(corpus),
        relogio,
    )
