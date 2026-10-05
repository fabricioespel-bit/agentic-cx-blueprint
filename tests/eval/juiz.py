"""Juiz LLM da avaliação (P5.4): a resposta é fiel aos trechos citados e responde?

Avalia só respostas com texto do redator (as que têm "Fontes consultadas"). Recusas,
negações e perguntas de roteamento são textos fixos: não há redação a julgar, e se a
recusa era devida é medido pela métrica de código ``comportamento``.

Roda dentro do agents-cli: só biblioteca padrão, google-genai e pydantic; os trechos
vêm de ``tests/eval/corpus_juiz.json`` (gerado por ``gerar_corpus_juiz.py``). Modelo
diferente do redator, temperatura 0. Calibrado contra rótulos humanos em
``tests/eval/calibracao/``.
"""

import json
import threading
from enum import StrEnum

from google import genai
from google.genai import types
from pydantic import BaseModel

MODELO = "gemini-2.5-pro"
CORPUS = "tests/eval/corpus_juiz.json"
RODAPE_FONTES = "Fontes consultadas: "

INSTRUCAO = """Você avalia respostas de um assistente de atendimento do Banco Exemplo.

Compare a resposta com os trechos citados como fonte e escolha um rótulo:
- ok: responde à pergunta e só afirma o que os trechos dizem.
- incompleto: responde, mas omite dos trechos citados informação que muda a decisão
  do cliente sobre a pergunta (um encargo, uma exceção, uma condição).
- excesso: responde, mas acrescenta uma situação diferente da perguntada (por
  exemplo, perguntou do pagamento mínimo e a resposta trata também do atraso).
  Detalhes da mesma situação, que o cliente precisaria saber, não são excesso.
- nao_responde: não responde ao que foi perguntado.
- infiel: afirma algo que os trechos não dizem, mesmo que pareça plausível.

Com mais de um problema, use o mais grave:
infiel > nao_responde > incompleto > excesso > ok.
Julgue só pelos trechos; não use conhecimento próprio sobre bancos. Os valores
(R$, %, números) vêm da tabela oficial e aparecem iguais nos trechos.
Explique em uma ou duas frases, citando a parte da resposta que motivou o rótulo."""


class Rotulo(StrEnum):
    OK = "ok"
    INCOMPLETO = "incompleto"
    EXCESSO = "excesso"
    NAO_RESPONDE = "nao_responde"
    INFIEL = "infiel"


# Nota pela gravidade: excesso é o problema mais leve (a resposta não engana, mas não é
# a ideal); os demais zeram.
NOTAS = {Rotulo.OK: 1.0, Rotulo.EXCESSO: 0.5}


class Veredito(BaseModel):
    rotulo: Rotulo
    explicacao: str


_local = threading.local()


def _cliente() -> genai.Client:
    # Um cliente por thread: o agents-cli avalia os casos em paralelo.
    cliente = getattr(_local, "cliente", None)
    if cliente is None:
        cliente = _local.cliente = genai.Client()
    return cliente


def _texto(conteudo) -> str:
    if isinstance(conteudo, str):
        return conteudo
    return "".join(p.get("text") or "" for p in (conteudo or {}).get("parts") or [])


def fontes_citadas(resposta: str) -> list[str]:
    """Fontes do rodapé, na forma "Título, Seção"."""
    if RODAPE_FONTES not in resposta:
        return []
    rodape = resposta.split(RODAPE_FONTES, 1)[1].strip().removesuffix(".")
    return [f.strip() for f in rodape.split(";") if f.strip()]


def montar_pedido(pergunta: str, resposta: str, trechos: dict[str, str]) -> str:
    corpo = resposta.split(RODAPE_FONTES, 1)[0].strip()
    blocos = "\n\n".join(f"[{nome}]\n{texto}" for nome, texto in trechos.items())
    return (
        f"Pergunta do cliente:\n{pergunta}\n\n"
        f"Resposta do assistente:\n{corpo}\n\n"
        f"Trechos citados como fonte:\n\n{blocos}"
    )


def evaluate(instance: dict) -> dict:
    resposta = _texto(instance.get("response"))
    citadas = fontes_citadas(resposta)
    if not citadas:
        return {"score": 1.0, "explanation": "rotulo: nao_se_aplica (texto fixo)"}
    with open(CORPUS, encoding="utf-8") as arquivo:
        corpus = json.load(arquivo)
    trechos = {nome: corpus.get(nome, "(trecho não encontrado)") for nome in citadas}
    pedido = montar_pedido(_texto(instance.get("prompt")), resposta, trechos)
    saida = _cliente().models.generate_content(
        model=MODELO,
        contents=pedido,
        config=types.GenerateContentConfig(
            system_instruction=INSTRUCAO,
            temperature=0,
            response_mime_type="application/json",
            response_schema=Veredito,
        ),
    )
    veredito = saida.parsed
    if veredito is None:
        return {"score": 0.0, "explanation": f"rotulo: erro; {saida.text or ''}"}
    return {
        "score": NOTAS.get(veredito.rotulo, 0.0),
        "explanation": f"rotulo: {veredito.rotulo.value}; {veredito.explicacao}",
    }
