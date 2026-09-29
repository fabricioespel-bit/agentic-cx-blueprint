"""Grafo do agente: o LLM classifica; política, confirmação e execução são código.

Um turno entra por ``entrada``. Sem pendência, a mensagem vai ao classificador (única
chamada ao LLM) e depois a ``decidir``. Com pendência (escolha de cartão ou confirmação),
vai direto a ``retomar``, sem LLM: a resposta do cliente é comparada por código.

Adequações do protótipo: a confirmação é por "SIM" digitado, com correspondência exata
(D5; em produção, botão do canal); a sessão é aberta como demonstração no primeiro turno
(em produção, pelo gateway); o texto chega ao LLM sem mascaramento (P4).
"""

import re
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.models import Gemini
from google.adk.workflow import Workflow
from google.genai import types
from pydantic import BaseModel, Field

from app.nucleo.catalogo import Catalogo, IntencaoDesconhecida, Tipo
from app.nucleo.politica import Resultado
from app.orquestrador import textos
from app.orquestrador.ambiente import Ambiente

# intenções cujo parâmetro é o final do cartão
PEDEM_CARTAO = {"consultar_limite", "bloquear_cartao_temporario"}
# Lista fechada de respostas que confirmam (D5)
CONFIRMA = {"sim"}
# Motivos de recusa do executor ligados à confirmação.
FALHAS_DE_CONFIRMACAO = {
    "confirmacao_ausente",
    "confirmacao_inexistente",
    "confirmacao_reutilizada",
    "confirmacao_expirada",
    "parametros_divergentes",
    "chave_em_conflito",
}
TIPOS = {"credito": "crédito", "debito": "débito"}


class Classificacao(BaseModel):
    intencao: str = Field(description="Id de uma das intenções da lista.")
    final_cartao: str | None = Field(
        default=None,
        description="Os 4 últimos dígitos do cartão, só se o cliente os informou.",
    )


INSTRUCAO = """Você classifica a mensagem de um cliente do Banco Exemplo.
Responda só com a classificação; não converse com o cliente.

Intenções possíveis:
{opcoes}

Regras:
- Escolha exatamente um id da lista.
- Se nenhuma se aplica, use fora_de_escopo.
- Preencha final_cartao só com 4 dígitos que o cliente escreveu; senão, deixe vazio.
"""


def criar_classificador(catalogo: Catalogo, modelo: Gemini) -> LlmAgent:
    opcoes = "\n".join(f"- {i.id}: {i.descricao}" for i in catalogo.intencoes)
    return LlmAgent(
        name="classificador",
        model=modelo,
        instruction=INSTRUCAO.format(opcoes=opcoes),
        output_schema=Classificacao,
        generate_content_config=types.GenerateContentConfig(temperature=0),
    )


def _mensagem(texto: str) -> Event:
    return Event(content=types.Content(role="model", parts=[types.Part(text=texto)]))


def _texto(conteudo: types.Content) -> str:
    return "".join(p.text or "" for p in conteudo.parts or []).strip()


def criar_workflow(ambiente: Ambiente, classificador: Any, nome: str) -> Workflow:
    """Monta o grafo. ``classificador``é o LLMAgent em produção e uma função nos testes."""

    def contexto(ctx: Context):
        return ambiente.cofre.resolver(ctx.state.get("sessao"))

    def prosseguir(ctx: Context, intencao_id: str, final: str | None) -> Event:
        """Com a intenção e os parâmetros completos: consulta ou pede confirmação."""
        intencao = ambiente.catalogo.obter(intencao_id)
        parametros = {"final_cartao": final} if intencao_id in PEDEM_CARTAO else {}
        if not intencao.escrita:
            pedido = {"intencao": intencao_id, "parametros": parametros}
            return Event(output=pedido, route="consultar")
        decisao = ambiente.politica.avaliar(intencao_id, parametros, contexto(ctx))
        if decisao.resultado is not Resultado.CONFIRMAR:
            return Event(
                output=textos.negacao(intencao_id, decisao.motivo), route="responder"
            )
        pendente = {
            "tipo": "confirmacao",
            "intencao": intencao_id,
            "parametros": parametros,
            "confirmacao": decisao.confirmacao.id,
        }
        return Event(
            output=textos.CONFIRMACAO.format(texto=decisao.confirmacao.texto),
            route="responder",
            state={"pendente": pendente},
        )

    def entrada(ctx: Context, node_input: types.Content) -> Event:
        estado = {}
        if not ctx.state.get("sessao"):
            estado["sessao"] = ambiente.abrir_sessao_demo(ctx.session.id)
        rota = "retomar" if ctx.state.get("pendente") else "classificar"
        return Event(output=_texto(node_input), route=rota, state=estado)

    def decidir(ctx: Context, node_input: dict) -> Event:
        classificacao = Classificacao.model_validate(node_input)
        try:
            intencao = ambiente.catalogo.obter(classificacao.intencao)
        except IntencaoDesconhecida:
            return Event(output=textos.NEGACAO_PADRAO, route="responder")
        if intencao.tipo is Tipo.FORA_DE_ESCOPO:
            return Event(output=textos.FORA_DE_ESCOPO, route="responder")
        decisao = ambiente.politica.verificar(intencao.id, contexto(ctx))
        if decisao.resultado is Resultado.NEGAR:
            return Event(
                output=textos.negacao(intencao.id, decisao.motivo), route="responder"
            )
        if intencao.tipo is Tipo.INFORMACAO:
            return Event(output=textos.INFORMACAO, route="responder")
        if intencao.id in PEDEM_CARTAO and not classificacao.final_cartao:
            return Event(output=intencao.id, route="escolher_cartao")
        return prosseguir(ctx, intencao.id, classificacao.final_cartao)

    async def escolher_cartao(ctx: Context, node_input: str):
        resposta = await ambiente.chamar("listar_cartoes", {}, ctx.state["sessao"])
        if not resposta.ok:
            yield _mensagem(textos.FALHA)
            return
        opcoes = " ou ".join(
            f"{c['final']} ({TIPOS.get(c['tipo'], c['tipo'])})"
            for c in resposta.dados["cartoes"]
        )
        yield _mensagem(textos.PERGUNTA_CARTAO.format(opcoes=opcoes))
        yield Event(state={"pendente": {"tipo": "cartao", "intencao": node_input}})

    async def retomar(ctx: Context, node_input: str) -> Event:
        pendente = ctx.state["pendente"]
        limpar = {"pendente": None}
        if pendente["tipo"] == "confirmacao":
            if node_input.strip().lower() in CONFIRMA:
                return Event(output=pendente, route="executar", state=limpar)
            return Event(output=textos.CANCELADO, route="responder", state=limpar)
        # Escolha de cartão: o final digitado precisa ser de um cartão do cliente.
        resposta = await ambiente.chamar("listar_cartoes", {}, ctx.state["sessao"])
        finais = (
            {c["final"] for c in resposta.dados["cartoes"]} if resposta.ok else set()
        )
        digitado = re.search(r"\b(\d{4})\b", node_input)
        if digitado is None or digitado.group(1) not in finais:
            return Event(
                output=textos.CARTAO_NAO_ENCONTRADO, route="responder", state=limpar
            )
        evento = prosseguir(ctx, pendente["intencao"], digitado.group(1))
        evento.actions.state_delta.setdefault("pendente", None)
        return evento

    def responder(node_input: str):
        yield _mensagem(node_input)

    async def consultar(ctx: Context, node_input: dict):
        ferramenta = {"listar_cartoes": "listar_cartoes"}.get(
            node_input["intencao"], "consultar_limite"
        )
        resposta = await ambiente.chamar(
            ferramenta, node_input["parametros"], ctx.state["sessao"]
        )
        if not resposta.ok:
            texto = (
                textos.CARTAO_NAO_ENCONTRADO
                if resposta.motivo == "cartao_nao_encontrado"
                else textos.negacao(node_input["intencao"], resposta.motivo)
            )
        elif ferramenta == "listar_cartoes":
            lista = ", ".join(
                f"final {c['final']} ({TIPOS.get(c['tipo'], c['tipo'])}, {c['situacao']})"
                for c in resposta.dados["cartoes"]
            )
            texto = textos.CARTOES.format(lista=lista)
        else:
            dados = resposta.dados
            texto = textos.LIMITE.format(
                final=dados["final"],
                total=textos.reais(dados["limite_total"]),
                disponivel=textos.reais(dados["limite_disponivel"]),
            )
        yield _mensagem(texto)

    async def executar(ctx: Context, node_input: dict):
        resposta = await ambiente.chamar(
            "bloquear_cartao",
            node_input["parametros"],
            ctx.state["sessao"],
            confirmacao=node_input["confirmacao"],
        )
        if not resposta.ok:
            confirmacao_falhou = resposta.motivo in FALHAS_DE_CONFIRMACAO
            yield _mensagem(
                textos.CONFIRMACAO_INVALIDA if confirmacao_falhou else textos.FALHA
            )
            return
        dados = resposta.dados
        modelo = (
            textos.BLOQUEADO
            if dados["estado"] == "concluida"
            else textos.EM_VERIFICACAO
        )
        yield _mensagem(
            modelo.format(final=dados["final"], protocolo=dados["protocolo"])
        )

    return Workflow(
        name=nome,
        edges=[
            ("START", entrada),
            (entrada, {"classificar": classificador, "retomar": retomar}),
            (classificador, decidir),
            (
                decidir,
                {
                    "responder": responder,
                    "consultar": consultar,
                    "escolher_cartao": escolher_cartao,
                },
            ),
            (
                retomar,
                {"responder": responder, "consultar": consultar, "executar": executar},
            ),
        ],
    )
