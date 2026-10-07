"""Grafo do agente: o LLM classifica; política, confirmação e execução são código.

Um turno entra por ``entrada``. Sem pendência, a mensagem vai ao classificador (única
chamada ao LLM) e depois a ``decidir``. Com pendência (escolha de cartão ou confirmação),
vai direto a ``retomar``, sem LLM: a resposta do cliente é comparada por código.

Adequações do protótipo: a confirmação é por "SIM" digitado, com correspondência exata
(D5; em produção, botão do canal); a sessão é aberta como demonstração no primeiro turno
(em produção, pelo gateway); o texto chega ao LLM sem mascaramento (P4).
"""

import asyncio
import re
import secrets
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.models import Gemini
from google.adk.workflow import Workflow
from google.genai import types
from pydantic import BaseModel, Field

from app.conhecimento.redator import montar_pedido, montar_revisao
from app.conhecimento.resposta import Resposta, fontes, preencher
from app.conhecimento.resposta import verificar as verificar_fundamentacao
from app.guardrails.mascaramento import CARTAO
from app.nucleo.catalogo import Catalogo, IntencaoDesconhecida, Tipo
from app.nucleo.politica import Resultado
from app.observabilidade.traces import tracer
from app.orquestrador import atendimento, textos
from app.orquestrador.ambiente import Ambiente

# Final de cartão vindo do classificador só vale com exatamente 4 dígitos (a política
# confere de novo pelo formato declarado no catálogo).
FINAL_CARTAO = re.compile(r"\d{4}")
# intenções cujo parâmetro é o final do cartão
PEDEM_CARTAO = {"consultar_limite", "bloquear_cartao_temporario"}
# Intenção com pré-check de situação do cartão (idempotência de negócio)
BLOQUEIO = "bloquear_cartao_temporario"
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
    # Escalonamento é saída transversal, não intenção: vem num campo à parte.
    pede_atendente: bool = Field(
        default=False,
        description="Verdadeiro só se o cliente pede para falar com uma pessoa.",
    )


INSTRUCAO = """Você classifica a mensagem de um cliente do Banco Exemplo.
Responda só com a classificação; não converse com o cliente.

Intenções possíveis:
{opcoes}

Regras:
- Escolha exatamente um id da lista.
- Se nenhuma se aplica, use fora_de_escopo.
- Preencha final_cartao só com 4 dígitos que o cliente escreveu; senão, deixe vazio.
- Marque pede_atendente só se o cliente pedir para falar com uma pessoa (atendente,
  humano, alguém); a intenção continua sendo a do pedido.
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


def criar_workflow(
    ambiente: Ambiente, classificador: Any, redator: Any, revisor: Any, nome: str
) -> Workflow:
    """Monta o grafo. Os nós com LLM (classificador, redator, revisor) são LlmAgent em
    produção e funções nos testes."""

    trechos_por_id = {t.id: t for t in ambiente.corpus.trechos}

    def marcar(ctx: Context, estado: dict | None = None, **campos: Any) -> dict:
        """Delta de estado que acrescenta campos ao resumo do turno (lido pela auditoria).

        Só o que não se lê na resposta: intenção, motivo de negação, execução.
        """
        estado = dict(estado or {})
        atual = estado.get("turno", ctx.state.get("turno") or {})
        estado["turno"] = {**atual, **campos}
        return estado

    def encaminhar(ctx: Context, motivo: str, modelo: str, **marcas: Any) -> Event:
        """Encaminha ao atendimento humano com resumo feito por código, sem LLM."""
        protocolo = f"ATD-{secrets.token_hex(4).upper()}"
        cliente = contexto(ctx)
        historico = ctx.state.get("historico") or []
        ultima = ctx.state.get("pergunta")
        ambiente.atendimento.gravar(
            {
                "protocolo": protocolo,
                "momento": ambiente.relogio().isoformat(),
                "sessao": ctx.session.id,
                "cliente_ref": cliente.cliente_ref,
                "motivo": motivo,
                "historico": historico,
                "resumo": atendimento.resumo(
                    protocolo=protocolo,
                    cliente_ref=cliente.cliente_ref,
                    canal=cliente.canal.value,
                    nivel=cliente.nivel_autenticacao,
                    motivo=motivo,
                    historico=historico,
                    ultima_mensagem=ultima,
                ),
            }
        )
        estado = marcar(
            ctx,
            {"atendimento": {"protocolo": protocolo}, "pendente": None},
            **marcas,
            motivo=motivo,
            encaminhamento={"protocolo": protocolo},
        )
        return Event(
            output=modelo.format(protocolo=protocolo), route="responder", state=estado
        )

    def saida(ctx: Context, texto: str):
        """Toda resposta ao cliente passa aqui: falhas seguidas encaminham; oferta de
        atendente vira pendência, aceita só por "sim" na próxima mensagem."""
        historico = ctx.state.get("historico") or []
        if atendimento.falhas_repetidas(historico, textos.desfecho(texto)):
            evento = encaminhar(ctx, "falhas_repetidas", textos.ENCAMINHADO_FALHAS)
            yield _mensagem(evento.output)
            yield Event(state=evento.actions.state_delta)
            return
        yield _mensagem(texto)
        if textos.OFERTA_ATENDENTE in texto:
            yield Event(state={"pendente": {"tipo": "oferta_atendente"}})

    async def filtrar(ctx: Context, texto: str, estado: dict) -> Event | None:
        """Filtro de entrada, só antes de um LLM. Barrada: texto fixo, sem LLM."""
        with tracer.start_as_current_span("filtro de entrada") as span:
            avaliacao = await asyncio.to_thread(ambiente.filtro.avaliar, texto)
            span.set_attribute("barrado", avaliacao.barrado)
            span.set_attribute("filtros", avaliacao.filtros)
            span.set_attribute("indisponivel", avaliacao.indisponivel)
        if avaliacao.indisponivel:
            estado.update(marcar(ctx, estado, filtro={"indisponivel": True}))
        if not avaliacao.barrado:
            return None
        motivo = "filtro:" + ",".join(avaliacao.filtros)
        estado = marcar(
            ctx, estado, motivo=motivo, filtro={"barrado": avaliacao.filtros}
        )
        return Event(output=textos.MENSAGEM_BARRADA, route="responder", state=estado)

    def contexto(ctx: Context):
        return ambiente.cofre.resolver(ctx.state.get("sessao"))

    async def ja_bloqueado(ctx: Context, final: str) -> bool:
        """Pré-check de experiência: a garantia é a recusa do executor."""
        resposta = await ambiente.chamar("listar_cartoes", {}, ctx.state["sessao"])
        if not resposta.ok:
            return False  # sem a lista, segue; o executor recusa se preciso
        return any(
            c["final"] == final and c["situacao"] == "bloqueado"
            for c in resposta.dados["cartoes"]
        )

    async def prosseguir(ctx: Context, intencao_id: str, final: str | None) -> Event:
        """Com a intenção e os parâmetros completos: consulta ou pede confirmação."""
        intencao = ambiente.catalogo.obter(intencao_id)
        parametros = {"final_cartao": final} if intencao_id in PEDEM_CARTAO else {}
        if not intencao.escrita:
            pedido = {"intencao": intencao_id, "parametros": parametros}
            return Event(output=pedido, route="consultar")
        if intencao_id == BLOQUEIO and await ja_bloqueado(ctx, final):
            return Event(
                output=textos.JA_BLOQUEADO.format(final=final), route="responder"
            )
        decisao = ambiente.politica.avaliar(intencao_id, parametros, contexto(ctx))
        if decisao.resultado is not Resultado.CONFIRMAR:
            return Event(
                output=textos.negacao(intencao_id, decisao.motivo),
                route="responder",
                state=marcar(ctx, motivo=decisao.motivo.value),
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

    async def entrada(ctx: Context, node_input: types.Content) -> Event:
        estado: dict[str, Any] = {"turno": {}}  # resumo novo a cada turno
        if not ctx.state.get("sessao"):
            estado["sessao"] = ambiente.abrir_sessao_demo(ctx.session.id)
        texto = _texto(node_input)
        if encaminhado := ctx.state.get("atendimento"):
            # Já com um atendente: o agente não responde por cima dele.
            return Event(
                output=textos.JA_ENCAMINHADO.format(protocolo=encaminhado["protocolo"]),
                route="responder",
                state=estado,
            )
        if CARTAO in texto:
            # Número completo de cartão (já trocado pelo plugin): não segue para o LLM.
            estado["pendente"] = None
            return Event(
                output=textos.NUMERO_DE_CARTAO, route="responder", state=estado
            )
        # O conhecimento busca pela mensagem do cliente, não pela intenção.
        estado["pergunta"] = texto
        if ctx.state.get("pendente"):
            return Event(output=texto, route="retomar", state=estado)
        if barrada := await filtrar(ctx, texto, estado):
            return barrada
        return Event(output=texto, route="classificar", state=estado)

    async def decidir(ctx: Context, node_input: dict) -> Event:
        classificacao = Classificacao.model_validate(node_input)
        marcas: dict[str, Any] = {"intencao": classificacao.intencao}
        if classificacao.pede_atendente:
            return encaminhar(ctx, "pedido_do_cliente", textos.ENCAMINHADO, **marcas)
        try:
            intencao = ambiente.catalogo.obter(classificacao.intencao)
        except IntencaoDesconhecida:
            estado = marcar(ctx, **marcas, motivo="intencao_desconhecida")
            return Event(output=textos.NEGACAO_PADRAO, route="responder", state=estado)
        if intencao.tipo is Tipo.FORA_DE_ESCOPO:
            estado = marcar(ctx, **marcas)
            return Event(output=textos.FORA_DE_ESCOPO, route="responder", state=estado)
        decisao = ambiente.politica.verificar(intencao.id, contexto(ctx))
        if decisao.resultado is Resultado.NEGAR:
            return Event(
                output=textos.negacao(intencao.id, decisao.motivo),
                route="responder",
                state=marcar(ctx, **marcas, motivo=decisao.motivo.value),
            )
        if intencao.tipo is Tipo.INFORMACAO:
            estado = marcar(ctx, **marcas)
            return Event(output=ctx.state["pergunta"], route="buscar", state=estado)
        final = classificacao.final_cartao
        if final is not None and not FINAL_CARTAO.fullmatch(final):
            final = None  # saída do LLM fora do formato: pergunta qual cartão
            marcas["final_descartado"] = True  # o fato, nunca o texto descartado
        if intencao.id in PEDEM_CARTAO and not final:
            estado = marcar(ctx, **marcas)
            return Event(output=intencao.id, route="escolher_cartao", state=estado)
        evento = await prosseguir(ctx, intencao.id, final)
        evento.actions.state_delta.update(
            marcar(ctx, evento.actions.state_delta, **marcas)
        )
        return evento

    async def escolher_cartao(ctx: Context, node_input: str):
        resposta = await ambiente.chamar("listar_cartoes", {}, ctx.state["sessao"])
        if not resposta.ok:
            for evento in saida(ctx, textos.FALHA):
                yield evento
            return
        opcoes = " ou ".join(
            f"{c['final']} ({TIPOS.get(c['tipo'], c['tipo'])})"
            for c in resposta.dados["cartoes"]
        )
        yield _mensagem(textos.PERGUNTA_CARTAO.format(opcoes=opcoes))
        yield Event(state={"pendente": {"tipo": "cartao", "intencao": node_input}})

    async def retomar(ctx: Context, node_input: str) -> Event:
        pendente = ctx.state["pendente"]
        if pendente["tipo"] == "oferta_atendente":
            if node_input.strip().lower() in CONFIRMA:
                return encaminhar(ctx, "aceite_da_oferta", textos.ENCAMINHADO)
            # Qualquer outra resposta: a oferta cai e a mensagem segue o caminho normal,
            # passando pelo filtro, porque vai para o classificador.
            estado: dict[str, Any] = {"pendente": None}
            if barrada := await filtrar(ctx, node_input, estado):
                return barrada
            return Event(output=node_input, route="classificar", state=estado)
        limpar = marcar(ctx, {"pendente": None}, intencao=pendente["intencao"])
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
        evento = await prosseguir(ctx, pendente["intencao"], digitado.group(1))
        evento.actions.state_delta.update(
            marcar(ctx, evento.actions.state_delta, intencao=pendente["intencao"])
        )
        evento.actions.state_delta.setdefault("pendente", None)
        return evento

    def buscar(node_input: str) -> Event:
        trechos = ambiente.buscador.buscar(node_input, ambiente.hoje())
        if not trechos:
            return Event(output=textos.SEM_FONTE, route="responder")
        consulta = {"pergunta": node_input, "trechos": [t.id for t in trechos]}
        return Event(
            output=montar_pedido(node_input, trechos),
            route="redigir",
            state={"conhecimento": consulta},
        )

    def avaliar(ctx: Context, node_input: Any):
        """Verifica a saída de um redator contra os trechos desta consulta."""
        consulta = ctx.state["conhecimento"]
        trechos = [trechos_por_id[i] for i in consulta["trechos"]]
        resposta = Resposta.model_validate(node_input or {"afirmacoes": []})
        problemas = verificar_fundamentacao(resposta, trechos)
        return consulta, trechos, resposta, problemas

    def aprovada(consulta: dict, resposta: Resposta) -> Event:
        citadas = [trechos_por_id[i] for i in fontes(resposta)]
        lista = "; ".join(f"{t.documento.titulo}, {t.secao}" for t in citadas)
        texto = preencher(resposta, ambiente.corpus.tabela)
        return Event(
            output=f"{texto}\n\n{textos.FONTES.format(lista=lista)}",
            route="responder",
            state={"conhecimento": consulta | {"fontes": fontes(resposta)}},
        )

    def verificar(ctx: Context, node_input: Any) -> Event:
        consulta, trechos, resposta, problemas = avaliar(ctx, node_input)
        if not problemas:
            return aprovada(consulta, resposta)
        if not resposta.afirmacoes:
            # Recusa honesta do redator: não há o que revisar. Mandar ao revisor o
            # pressiona a responder com o que houver nos trechos, mesmo fora do tema.
            return Event(
                output=textos.SEM_FONTE,
                route="responder",
                state={"conhecimento": consulta | {"problemas": problemas}},
            )
        return Event(
            output=montar_revisao(consulta["pergunta"], trechos, resposta, problemas),
            route="revisar",
            state={"conhecimento": consulta | {"problemas": problemas}},
        )

    def verificar_revisao(ctx: Context, node_input: Any) -> Event:
        consulta, _, resposta, problemas = avaliar(ctx, node_input)
        if not problemas:
            return aprovada(consulta, resposta)
        return Event(
            output=textos.SEM_FONTE,
            route="responder",
            state={"conhecimento": consulta | {"problemas_revisao": problemas}},
        )

    def responder(ctx: Context, node_input: str):
        yield from saida(ctx, node_input)

    async def consultar(ctx: Context, node_input: dict):
        ferramenta = {"listar_cartoes": "listar_cartoes"}.get(
            node_input["intencao"], "consultar_limite"
        )
        resposta = await ambiente.chamar(
            ferramenta, node_input["parametros"], ctx.state["sessao"]
        )
        if not resposta.ok:
            yield Event(state=marcar(ctx, motivo=resposta.motivo))
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
        for evento in saida(ctx, texto):
            yield evento

    async def executar(ctx: Context, node_input: dict):
        resposta = await ambiente.chamar(
            "bloquear_cartao",
            node_input["parametros"],
            ctx.state["sessao"],
            confirmacao=node_input["confirmacao"],
        )
        if not resposta.ok:
            yield Event(state=marcar(ctx, motivo=resposta.motivo))
            if resposta.motivo == "cartao_ja_bloqueado":
                final = node_input["parametros"]["final_cartao"]
                texto = textos.JA_BLOQUEADO.format(final=final)
            elif resposta.motivo in FALHAS_DE_CONFIRMACAO:
                texto = textos.CONFIRMACAO_INVALIDA
            else:
                texto = textos.FALHA
            for evento in saida(ctx, texto):
                yield evento
            return
        dados = resposta.dados
        execucao = {"estado": dados["estado"], "protocolo": dados["protocolo"]}
        yield Event(state=marcar(ctx, execucao=execucao))
        modelo = (
            textos.BLOQUEADO
            if dados["estado"] == "concluida"
            else textos.EM_VERIFICACAO
        )
        texto = modelo.format(final=dados["final"], protocolo=dados["protocolo"])
        for evento in saida(ctx, texto):
            yield evento

    return Workflow(
        name=nome,
        edges=[
            ("START", entrada),
            (
                entrada,
                {
                    "classificar": classificador,
                    "retomar": retomar,
                    "responder": responder,
                },
            ),
            (classificador, decidir),
            (
                decidir,
                {
                    "responder": responder,
                    "consultar": consultar,
                    "escolher_cartao": escolher_cartao,
                    "buscar": buscar,
                },
            ),
            (buscar, {"responder": responder, "redigir": redator}),
            (redator, verificar),
            (verificar, {"responder": responder, "revisar": revisor}),
            (revisor, verificar_revisao),
            (verificar_revisao, {"responder": responder}),
            (
                retomar,
                {
                    "responder": responder,
                    "consultar": consultar,
                    "executar": executar,
                    "classificar": classificador,
                },
            ),
        ],
    )
