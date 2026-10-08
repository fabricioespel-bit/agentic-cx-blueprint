"""Pensamento do classificador: acertos e latência por nível (passo de latência).

    uv run python tests/eval/pensamento_classificador.py [--repeticoes 2]

Chama o Gemini como o classificador chama (mesma instrução, mesmo esquema de saída,
temperatura 0) sobre mensagens já mascaradas, com a classificação esperada, em três níveis
de pensamento: o padrão do modelo, LOW e MINIMAL. Os níveis rodam um depois do outro, para
não disputarem a mesma janela de latência do serviço. Custa frações de centavo por chamada.

Aproximação: o ADK acrescenta à instrução algumas linhas próprias; aqui vai só a nossa.
"""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.nucleo.catalogo import carregar_catalogo
from app.observabilidade.relatorio import percentil
from app.orquestrador.fluxo import INSTRUCAO, Classificacao

CASOS = Path(__file__).parent / "datasets" / "classificador.json"
MODELO = "gemini-3.8-flash"
NIVEIS = {
    "padrão": None,
    "LOW": types.ThinkingLevel.LOW,
    "MINIMAL": types.ThinkingLevel.MINIMAL,
}
SIMULTANEAS = 4


def acertou(caso: dict, saida: dict) -> bool:
    return (
        all(saida[campo] == valor for campo, valor in caso["esperado"].items())
        and ("final_cartao" in caso["esperado"] or saida["final_cartao"] is None)
        and ("pede_atendente" in caso["esperado"] or not saida["pede_atendente"])
    )


async def medir(cliente, nivel, casos: list[dict], repeticoes: int, instrucao: str):
    config = types.GenerateContentConfig(
        system_instruction=instrucao,
        temperature=0,
        response_mime_type="application/json",
        response_schema=Classificacao,
        thinking_config=types.ThinkingConfig(thinking_level=nivel) if nivel else None,
    )
    vagas = asyncio.Semaphore(SIMULTANEAS)

    async def uma(caso: dict):
        async with vagas:
            inicio = time.monotonic()
            resposta = await cliente.aio.models.generate_content(
                model=MODELO, contents=caso["mensagem"], config=config
            )
            ms = (time.monotonic() - inicio) * 1000
        saida = Classificacao.model_validate_json(resposta.text).model_dump()
        pensamento = resposta.usage_metadata.thoughts_token_count or 0
        return caso, saida, ms, pensamento

    return await asyncio.gather(*(uma(c) for c in casos for _ in range(repeticoes)))


async def principal(repeticoes: int) -> None:
    load_dotenv()
    cliente = genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
    )
    opcoes = "\n".join(
        f"- {i.id}: {i.descricao}" for i in carregar_catalogo().intencoes
    )
    instrucao = INSTRUCAO.format(opcoes=opcoes)
    casos = json.loads(CASOS.read_text(encoding="utf-8"))["casos"]

    print("| Nível | Chamadas | Acertos | p50 | p95 | Pensamento (média) |")
    print("|---|---|---|---|---|---|")
    erros = {}
    for nome, nivel in NIVEIS.items():
        try:
            resultados = await medir(cliente, nivel, casos, repeticoes, instrucao)
        except Exception as erro:  # nível não aceito pelo modelo, por exemplo
            print(f"| {nome} | erro: {type(erro).__name__}: {str(erro)[:80]} | | | | |")
            continue
        ms = [r[2] for r in resultados]
        certos = sum(acertou(c, s) for c, s, _, _ in resultados)
        pensamento = sum(r[3] for r in resultados) / len(resultados)
        print(
            f"| {nome} | {len(resultados)} | {certos}/{len(resultados)} | "
            f"{percentil(ms, 50) / 1000:.1f} s | {percentil(ms, 95) / 1000:.1f} s | "
            f"{pensamento:.0f} |"
        )
        erros[nome] = [(c["id"], s) for c, s, _, _ in resultados if not acertou(c, s)]

    for nome, lista in erros.items():
        for caso, saida in lista:
            print(f"- {nome}, {caso}: {json.dumps(saida, ensure_ascii=False)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeticoes", type=int, default=2)
    asyncio.run(principal(parser.parse_args().repeticoes))
