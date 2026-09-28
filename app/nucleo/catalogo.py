"""Catálogo de intenções e piso de invariantes (decisão K1).

O catálogo é configuração: diz, por intenção, o tipo, o risco, a autenticação exigida, os
canais, os limites e a fase de liberação. O piso de invariantes é código: regras que nenhuma
configuração sobrescreve. Um catálogo que viola o piso não carrega.

Negação por padrão: intenção que não está no catálogo levanta ``IntencaoDesconhecida``.

Mock: em produção o catálogo é publicado assinado e somente leitura; aqui é lido de um
arquivo YAML local, sem verificação de assinatura.
"""

from enum import StrEnum
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

CAMINHO_PADRAO = (
    Path(__file__).resolve().parents[2] / "config" / "catalogo" / "cartoes.yaml"
)


class Tipo(StrEnum):
    INFORMACAO = "informacao"
    CONSULTA = "consulta"
    TRANSACAO = "transacao"
    FORA_DE_ESCOPO = "fora_de_escopo"


class Risco(StrEnum):
    BAIXO = "baixo"
    MEDIO = "medio"
    ALTO = "alto"


class Canal(StrEnum):
    WHATSAPP = "whatsapp"
    APP = "app"


class Fase(StrEnum):
    SHADOW = "shadow"
    ASSISTIDO = "assistido"
    AUTONOMO = "autonomo"


class ViolacaoDeInvariante(ValueError):
    """Configuração que contraria o piso de invariantes."""


class IntencaoDesconhecida(LookupError):
    """Intenção fora do catálogo: negada por padrão."""


class Intencao(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    descricao: str
    tipo: Tipo
    risco: Risco
    nivel_autenticacao: int = Field(ge=0, le=3)
    canais: frozenset[Canal] = Field(min_length=1)
    fase: Fase
    reversivel: bool = True
    exige_confirmacao: bool = False
    limite_diario: int | None = Field(default=None, ge=1)
    ferramenta: str | None = None
    texto_confirmacao: str | None = None

    @property
    def escrita(self) -> bool:
        return self.tipo is Tipo.TRANSACAO

    @model_validator(mode="after")
    def _piso(self) -> Self:
        # Invariantes por intenção. Levantam ValueError para o Pydantic agregar ao erro de
        # validação; a mensagem começa com "invariante" para ser rastreável.
        if self.escrita and not self.exige_confirmacao:
            raise ValueError(f"invariante: transação '{self.id}' sem confirmação")
        if self.escrita and not self.texto_confirmacao:
            raise ValueError(
                f"invariante: transação '{self.id}' sem texto de confirmação"
            )
        if self.escrita and not self.reversivel and self.nivel_autenticacao < 3:
            raise ValueError(
                f"invariante: transação irreversível '{self.id}' abaixo do nível 3"
            )
        if self.tipo in (Tipo.CONSULTA, Tipo.TRANSACAO) and self.nivel_autenticacao < 1:
            raise ValueError(
                f"invariante: '{self.id}' acessa dados do cliente com nível 0"
            )
        if self.tipo in (Tipo.CONSULTA, Tipo.TRANSACAO) and not self.ferramenta:
            raise ValueError(f"invariante: '{self.id}' sem ferramenta associada")
        if not self.escrita and self.limite_diario is not None:
            raise ValueError(f"'{self.id}': limite diário só se aplica a transações")
        return self


class Catalogo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    versao: str
    area: str
    intencoes: tuple[Intencao, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ids_unicos(self) -> Self:
        ids = [i.id for i in self.intencoes]
        repetidos = sorted({i for i in ids if ids.count(i) > 1})
        if repetidos:
            raise ValueError(f"intenções repetidas: {', '.join(repetidos)}")
        return self

    def obter(self, intencao_id: str) -> Intencao:
        for intencao in self.intencoes:
            if intencao.id == intencao_id:
                return intencao
        raise IntencaoDesconhecida(intencao_id)

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(i.id for i in self.intencoes)


def validar_publicacao(novo: Catalogo, anterior: Catalogo | None) -> None:
    """Invariante entre versões: intenção nova entra em shadow.

    Chamada no processo de publicação, comparando com a versão em produção.
    """
    existentes = anterior.ids if anterior else frozenset()
    fora_de_shadow = sorted(
        i.id
        for i in novo.intencoes
        if i.id not in existentes and i.fase is not Fase.SHADOW
    )
    if fora_de_shadow:
        raise ViolacaoDeInvariante(
            f"intenção nova precisa entrar em shadow: {', '.join(fora_de_shadow)}"
        )


def carregar_catalogo(caminho: Path = CAMINHO_PADRAO) -> Catalogo:
    with caminho.open(encoding="utf-8") as f:
        return Catalogo.model_validate(yaml.safe_load(f))
