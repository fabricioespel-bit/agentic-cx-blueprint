"""Corpus de conhecimento: tabela oficial de valores e documentos divididos em trechos.

Faz a ingestão (decisão G1): valida metadados, vigência e marcadores e divide cada
documento em trechos pelas seções ``##``. Números vivem só na tabela; o corpo dos
documentos cita as chaves como ``{{chave}}`` e não pode ter dígitos. Corpus com problema
não carrega, e o erro lista todos os problemas de uma vez, para o autor corrigir numa
rodada só.

Mock: em produção estas regras rodam no pipeline de publicação (autoria em Word, com
aprovação) e os trechos vão para o RAG Engine; aqui, são lidos de arquivos locais.
"""

import re
import unicodedata
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

CAMINHO_PADRAO = Path(__file__).resolve().parents[2] / "config" / "conhecimento"

Chave = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
MARCADOR = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
CABECALHO = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", flags=re.DOTALL)
SECAO = re.compile(r"^## +(.+?)\s*$", flags=re.MULTILINE)


class TipoValor(StrEnum):
    REAIS = "reais"
    PERCENTUAL = "percentual"
    INTEIRO = "inteiro"


class CorpusInvalido(ValueError):
    """Corpus que não pode ser publicado; ``problemas`` lista cada motivo."""

    def __init__(self, problemas: list[str]):
        super().__init__("\n".join(problemas))
        self.problemas = problemas


class Valor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    descricao: str = Field(min_length=1)
    tipo: TipoValor
    valor: Decimal

    @model_validator(mode="after")
    def _inteiro(self) -> Self:
        if self.tipo is TipoValor.INTEIRO and self.valor != self.valor.to_integral():
            raise ValueError("valor do tipo inteiro com casas decimais")
        return self


class TabelaValores(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    versao: str
    vigente_desde: date
    dono: str = Field(min_length=1)
    valores: dict[Chave, Valor] = Field(min_length=1)


class Documento(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    titulo: str = Field(min_length=1)
    dono: str = Field(min_length=1)
    versao: str
    vigente_desde: date
    vigente_ate: date | None = None

    @model_validator(mode="after")
    def _vigencia(self) -> Self:
        if self.vigente_ate is not None and self.vigente_ate < self.vigente_desde:
            raise ValueError("vigente_ate anterior a vigente_desde")
        return self

    def vigente_em(self, dia: date) -> bool:
        return self.vigente_desde <= dia and (
            self.vigente_ate is None or dia <= self.vigente_ate
        )


class Trecho(BaseModel):
    """Unidade de busca e de citação: uma seção ``##`` de um documento."""

    model_config = ConfigDict(frozen=True)

    id: str  # "documento#secao", estável entre versões enquanto o título não mudar
    documento: Documento
    secao: str
    texto: str

    @property
    def marcadores(self) -> frozenset[str]:
        return frozenset(MARCADOR.findall(self.texto))


class Corpus(BaseModel):
    model_config = ConfigDict(frozen=True)

    tabela: TabelaValores
    trechos: tuple[Trecho, ...]

    def vigentes(self, dia: date) -> tuple[Trecho, ...]:
        return tuple(t for t in self.trechos if t.documento.vigente_em(dia))


def ler_documento(nome: str, conteudo: str, tabela: TabelaValores) -> list[Trecho]:
    """Valida um documento e o divide em trechos. Levanta ``CorpusInvalido``."""

    conteudo = conteudo.replace("\r\n", "\n")
    partes = CABECALHO.match(conteudo)
    if partes is None:
        raise CorpusInvalido([f"{nome}: sem cabeçalhos entre linhas ---"])
    cabecalho, corpo = yaml.safe_load(partes.group(1)), partes.group(2)
    try:
        documento = Documento.model_validate(cabecalho)
    except ValidationError as erro:
        raise CorpusInvalido(
            [f"{nome}: cabeçalho: {_campo(e)}: {e['msg']}" for e in erro.errors()]
        ) from erro

    problemas = []
    antes, *resto = SECAO.split(corpo)
    if antes.strip():
        problemas.append(f"{nome}: texto antes da primeira seção ##")
    if not resto:
        problemas.append(f"{nome}: nenhuma seção ##")

    trechos, vistos = [], set()
    for titulo, bruto in zip(resto[0::2], resto[1::2], strict=True):
        texto = " ".join(bruto.split())
        local = f"{nome}, seção '{titulo}'"
        trecho_id = f"{documento.id}#{_slug(titulo)}"
        if not texto:
            problemas.append(f"{local}: seção vazia")
        if trecho_id in vistos:
            problemas.append(f"{local}: título repetido")
        vistos.add(trecho_id)
        sem_marcadores = MARCADOR.sub("", f"{titulo} {texto}")
        if re.search(r"\d", sem_marcadores):
            problemas.append(f"{local}: número fora de marcador; use uma {{{{chave}}}}")
        if "{{" in sem_marcadores or "}}" in sem_marcadores:
            problemas.append(f"{local}: marcador malformado")
        desconhecidas = sorted(set(MARCADOR.findall(texto)) - tabela.valores.keys())
        if desconhecidas:
            problemas.append(
                f"{local}: chaves fora da tabela: {', '.join(desconhecidas)}"
            )
        trechos.append(
            Trecho(id=trecho_id, documento=documento, secao=titulo, texto=texto)
        )
    if problemas:
        raise CorpusInvalido(problemas)
    return trechos


def carregar_corpus(pasta: Path = CAMINHO_PADRAO) -> Corpus:
    with (pasta / "valores.yaml").open(encoding="utf-8") as f:
        tabela = TabelaValores.model_validate(yaml.safe_load(f))
    problemas: list[str] = []
    trechos: list[Trecho] = []
    for caminho in sorted((pasta / "documentos").glob("*.md")):
        try:
            lidos = ler_documento(caminho.name, caminho.read_text("utf-8"), tabela)
        except CorpusInvalido as erro:
            problemas.extend(erro.problemas)
            continue
        if lidos[0].documento.id != caminho.stem:
            problemas.append(f"{caminho.name}: id diferente do nome do arquivo")
        trechos.extend(lidos)
    if not trechos and not problemas:
        problemas.append("nenhum documento em documentos/")
    if problemas:
        raise CorpusInvalido(problemas)
    return Corpus(tabela=tabela, trechos=tuple(trechos))


def _campo(erro: Any) -> str:
    return ".".join(str(p) for p in erro["loc"]) or "cabeçalho"


def _slug(titulo: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")
