from datetime import date

import pytest
import yaml
from pydantic import ValidationError

from app.conhecimento.corpus import (
    Corpus,
    CorpusInvalido,
    TabelaValores,
    carregar_corpus,
    ler_documento,
)

TABELA = TabelaValores.model_validate(
    {
        "versao": "t",
        "vigente_desde": "2026-09-01",
        "dono": "produtos",
        "valores": {
            "anuidade": {"descricao": "Anuidade", "tipo": "reais", "valor": "19.90"},
            "parcelas": {"descricao": "Parcelas", "tipo": "inteiro", "valor": 12},
        },
    }
)

CABECALHO = {
    "id": "doc",
    "titulo": "Documento de teste",
    "dono": "produtos",
    "versao": "t",
    "vigente_desde": "2026-09-01",
}

CORPO = "## Anuidade\n\nSão {{parcelas}} parcelas de\n{{anuidade}}.\n"


def documento(corpo: str = CORPO, **campos) -> str:
    """Monta um documento; campo=None remove o campo do cabeçalho."""
    cabecalho = {k: v for k, v in (CABECALHO | campos).items() if v is not None}
    linhas = "\n".join(f"{k}: {v}" for k, v in cabecalho.items())
    return f"---\n{linhas}\n---\n\n{corpo}"


def ler(texto: str):
    return ler_documento("doc.md", texto, TABELA)


def problemas(texto: str) -> list[str]:
    with pytest.raises(CorpusInvalido) as erro:
        ler(texto)
    return erro.value.problemas


def test_corpus_do_repositorio_carrega():
    corpus = carregar_corpus()
    ids = [t.id for t in corpus.trechos]
    assert len(ids) == len(set(ids))
    anuidade = next(t for t in corpus.trechos if t.id == "cartao-classico#anuidade")
    assert anuidade.marcadores == {"parcelas_anuidade", "anuidade_classico"}


def test_divide_por_secao_com_id_sem_acento_e_texto_corrido():
    [trecho] = ler(documento("## Isenção da anuidade\n\nLinha um\nlinha dois.\n"))
    assert trecho.id == "doc#isencao-da-anuidade"
    assert trecho.texto == "Linha um linha dois."
    assert trecho.documento.dono == "produtos"


@pytest.mark.parametrize(
    "corpo",
    ["## Anuidade\n\nCusta R$ 19,90.\n", "## Tarifa de 2026\n\nTexto.\n"],
    ids=["no_texto", "no_titulo"],
)
def test_numero_fora_de_marcador_recusado(corpo):
    [problema] = problemas(documento(corpo))
    assert "número fora de marcador" in problema


def test_chave_fora_da_tabela_recusada():
    [problema] = problemas(documento("## Anuidade\n\nCusta {{anuidade_gold}}.\n"))
    assert "anuidade_gold" in problema


@pytest.mark.parametrize("marcador", ["{{ anuidade }}", "{{anuidade", "{{Anuidade}}"])
def test_marcador_malformado_recusado(marcador):
    [problema] = problemas(documento(f"## Anuidade\n\nCusta {marcador}.\n"))
    assert "malformado" in problema


@pytest.mark.parametrize("campo", ["dono", "vigente_desde"])
def test_cabecalho_sem_campo_obrigatorio_recusado(campo):
    [problema] = problemas(documento(**{campo: None}))
    assert campo in problema


def test_vigencia_invertida_recusada():
    [problema] = problemas(documento(vigente_ate="2026-08-01"))
    assert "vigente_ate anterior" in problema


def test_problemas_do_documento_sao_reunidos():
    corpo = "Texto solto.\n\n## Anuidade\n\nCusta {{gold}} ou R$ 10.\n"
    assert len(problemas(documento(corpo))) == 3  # fora de seção, número, chave


def test_documento_sem_secao_recusado():
    assert any("nenhuma seção" in p for p in problemas(documento("Só texto.\n")))


def test_final_de_linha_do_windows_aceito():
    [trecho] = ler(documento().replace("\n", "\r\n"))
    assert trecho.id == "doc#anuidade"


def test_vigencia_filtra_na_busca_nao_na_carga():
    corpus = Corpus(
        tabela=TABELA, trechos=tuple(ler(documento(vigente_ate="2026-12-31")))
    )
    assert corpus.vigentes(date(2026, 8, 31)) == ()
    assert len(corpus.vigentes(date(2026, 9, 1))) == 1
    assert corpus.vigentes(date(2027, 1, 1)) == ()


def test_inteiro_com_casas_decimais_recusado():
    valores = {"parcelas": {"descricao": "P", "tipo": "inteiro", "valor": "12.5"}}
    with pytest.raises(ValidationError, match="inteiro"):
        TabelaValores.model_validate(
            TABELA.model_dump(mode="json") | {"valores": valores}
        )


def test_pasta_reune_problemas_de_todos_os_arquivos(tmp_path):
    (tmp_path / "documentos").mkdir()
    tabela = yaml.safe_dump(TABELA.model_dump(mode="json"))
    (tmp_path / "valores.yaml").write_text(tabela, "utf-8")
    (tmp_path / "documentos" / "outro-nome.md").write_text(documento(), "utf-8")
    ruim = documento("## Anuidade\n\nCusta R$ 10.\n")
    (tmp_path / "documentos" / "doc.md").write_text(ruim, "utf-8")
    with pytest.raises(CorpusInvalido) as erro:
        carregar_corpus(tmp_path)
    assert len(erro.value.problemas) == 2  # id ≠ nome do arquivo; número solto
