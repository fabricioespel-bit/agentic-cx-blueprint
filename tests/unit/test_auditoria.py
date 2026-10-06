"""Trilha de auditoria (P4.2): registro, cadeia de hashes e destinos. Sem Google Cloud."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.auditoria.destinos import DestinoArquivo, DestinoGoogle
from app.auditoria.registro import (
    GENESE,
    desfecho,
    metadados,
    montar_registro,
    verificar_cadeia,
)
from app.orquestrador import textos


def cadeia(n: int) -> list[dict]:
    registros, anterior = [], GENESE
    for i in range(1, n + 1):
        registro = montar_registro(
            sessao="s1",
            sequencia=i,
            momento=datetime(2026, 10, 6, 12, i, tzinfo=UTC),
            cliente_ref="cli-1",
            mensagem=f"mensagem {i} com [CPF]",
            resposta=textos.CANCELADO,
            turno={"intencao": "bloquear_cartao_temporario"},
            conhecimento=None,
            chamadas_llm=["classificador"],
            hash_anterior=anterior,
        )
        registros.append(registro)
        anterior = registro["hash"]
    return registros


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [
        ("Texto.\n\n" + textos.FONTES.format(lista="X, Y"), "respondido"),
        (textos.SEM_FONTE, "sem_fonte"),
        (textos.NUMERO_DE_CARTAO, "aviso_cartao"),
        (textos.PERGUNTA_CARTAO.format(opcoes="1234 (crédito)"), "pergunta_cartao"),
        (
            textos.CONFIRMACAO.format(texto="Bloquear o cartão final 1234?"),
            "confirmacao_pedida",
        ),
        (textos.BLOQUEADO.format(final="1234", protocolo="PRT-1"), "executado"),
        (
            textos.EM_VERIFICACAO.format(final="1234", protocolo="PRT-1"),
            "execucao_incerta",
        ),
        (textos.NEGACOES_POR_INTENCAO["desbloquear_cartao"], "negado"),
        ("texto que não é de nenhum modelo", "outro"),
    ],
)
def test_desfecho_pelo_texto_fixo(resposta, esperado):
    assert desfecho(resposta) == esperado


def test_cadeia_integra():
    assert verificar_cadeia(cadeia(3)) is None


def test_conteudo_alterado_e_detectado():
    registros = cadeia(3)
    registros[1]["intencao"] = "desbloquear_cartao"
    assert verificar_cadeia(registros) == "sequência 2: conteúdo alterado"


def test_registro_apagado_e_detectado():
    registros = cadeia(3)
    del registros[1]
    assert verificar_cadeia(registros) == "sequência 2: encontrada 3"


def test_reescrever_com_hash_novo_quebra_o_elo_seguinte():
    # Quem altera e recalcula o hash do registro 2 ainda quebra o elo do 3.
    registros = cadeia(3)
    registros[1]["intencao"] = "desbloquear_cartao"
    registros[1]["hash"] = montar_registro(
        **{k: registros[1][k] for k in ("sessao", "sequencia", "mensagem", "resposta")},
        momento=datetime(2026, 10, 6, 12, 2, tzinfo=UTC),
        cliente_ref="cli-1",
        turno={"intencao": "desbloquear_cartao"},
        conhecimento=None,
        chamadas_llm=["classificador"],
        hash_anterior=registros[0]["hash"],
    )["hash"]
    assert verificar_cadeia(registros) == "sequência 3: elo com o anterior quebrado"


def test_metadados_sem_mensagem_nem_resposta():
    linha = metadados(cadeia(1)[0], "gs://b/o.json")
    assert "mensagem" not in linha and "resposta" not in linha
    assert linha["objeto"] == "gs://b/o.json"
    assert linha["intencao"] == "bloquear_cartao_temporario"


def test_diario_local_so_acrescenta(tmp_path):
    diario = DestinoArquivo(tmp_path / "diario.jsonl")
    for registro in cadeia(2):
        diario.gravar(registro)
    assert verificar_cadeia(diario.ler()) is None


class Blob:
    def __init__(self, nome, gravados):
        self.nome, self.gravados = nome, gravados

    def upload_from_string(self, dados, content_type, if_generation_match):
        self.gravados.append((self.nome, if_generation_match))


def destino_falso(erros_bq=()):
    gravados, linhas = [], []
    storage = SimpleNamespace(
        bucket=lambda nome: SimpleNamespace(blob=lambda n: Blob(n, gravados))
    )
    bigquery = SimpleNamespace(
        insert_rows_json=lambda tabela, rows: linhas.extend(rows) or list(erros_bq)
    )
    destino = DestinoGoogle("p", "p-auditoria", "p.auditoria.turnos", storage, bigquery)
    return destino, gravados, linhas


def test_destino_google_grava_uma_vez_e_manda_metadados():
    destino, gravados, linhas = destino_falso()
    destino.gravar(cadeia(1)[0])
    assert gravados == [("2026-10-06/s1/000001.json", 0)]
    assert linhas[0]["objeto"] == "gs://p-auditoria/2026-10-06/s1/000001.json"
    assert "mensagem" not in linhas[0]


def test_destino_google_acusa_recusa_do_bigquery():
    destino, _, _ = destino_falso(erros_bq=[{"erro": "x"}])
    with pytest.raises(RuntimeError, match="BigQuery recusou"):
        destino.gravar(cadeia(1)[0])


def test_esquema_do_bigquery_tem_exatamente_as_colunas_dos_metadados():
    # Se um campo mudar em metadados(), a tabela precisa mudar junto.
    esquema = Path(__file__).parents[2] / "config" / "auditoria" / "turnos.schema.json"
    colunas = {c["name"] for c in json.loads(esquema.read_text(encoding="utf-8"))}
    assert set(metadados(cadeia(1)[0], "gs://b/o.json")) == colunas
