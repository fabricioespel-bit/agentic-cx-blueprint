# Evidência: trilha de auditoria (5 e 6/out/2026)

Um registro por turno, sem dado pessoal em claro, encadeado por hash na sessão, gravado no Cloud Storage com
retenção travada e com os metadados no BigQuery, ambos em `southamerica-east1`. Plugin do ADK no fim do turno
(`app/auditoria/`). Dados fictícios.

## Infraestrutura

- Bucket com acesso uniforme, prevenção de acesso público e **retenção de 1 dia travada** (irreversível; em
  produção, o prazo regulatório).
- Dataset e tabela no BigQuery particionada por dia e agrupada por sessão e cliente; o esquema
  (`config/auditoria/turnos.schema.json`) tem um teste que o compara com os metadados gravados.
- Conta do agente no CI: só `storage.objectCreator` no bucket (cria, não lê, não apaga) e
  `bigquery.dataEditor` na tabela.

## Validação de ponta a ponta

Uma conversa de três turnos ("bloqueia meu cartão" → "o 1234, meu CPF é 529.982.247-25" → "não") e uma
pergunta com nome completo, contra o agente local:

```
validacao-conversa 1 pergunta_cartao    | bloqueia meu cartão
validacao-conversa 2 confirmacao_pedida | o 1234, meu CPF é [CPF]
validacao-conversa 3 cancelado          | não
validacao-nome     1 respondido         | Sou a [NOME], qual a anuidade do cartão Clássico?
```

No BigQuery, a cadeia aparece elo por elo (o `anterior` de cada registro é o `hash` do anterior da sessão):

```
validacao-conversa | 1 | pergunta_cartao    | cli-1 | hash 2963fae015c0 | anterior 000000000000
validacao-conversa | 2 | confirmacao_pedida | cli-1 | hash dfd125368662 | anterior 2963fae015c0
validacao-conversa | 3 | cancelado          | cli-1 | hash 608237178b9b | anterior dfd125368662
validacao-nome     | 1 | respondido         | cli-1 | hash 1349cfa2fab3 | anterior 000000000000
```

**Imutabilidade, testada com a conta dona do projeto.** A tentativa de sobrescrever e a de apagar o registro 2
foram recusadas: *"Object … is subject to bucket's retention policy … and cannot be deleted or overwritten until
2026-10-07T10:37"*. O conteúdo seguiu o original.

**Verificador** (`uv run python -m app.auditoria.verificar <dia>`): lê os registros do bucket, confere a cadeia
de cada sessão e confere que o BigQuery tem as mesmas linhas com os mesmos hashes. Depois da avaliação no CI do
mesmo dia: *"29 sessões, 31 registros no bucket — trilha íntegra"* (2 sessões da validação local e 27 gravadas
pelo CI, com a conta de permissão mínima).

## Achados

**1. O agente subia localmente sem o SDP e sem a auditoria no Google Cloud, sem aviso.** O diário local tinha
33 registros e o bucket, nenhum; no diário, "Sou a Maria Aparecida dos Santos" em claro (o e-mail, coberto
pelas regras locais, estava mascarado). Causa: o `app/__init__.py` importa o agente antes de o
`fast_api_app.py` carregar o `.env`, e o agente lia `GOOGLE_CLOUD_PROJECT` na importação. O Gemini funcionava
porque a biblioteca dele lê as variáveis na hora da chamada. No CI, as variáveis vêm do workflow e o problema não
existia. Correção: o agente carrega o `.env` antes de ler as variáveis e registra na partida quais proteções
estão ativas (aviso explícito se o mascaramento estiver só com as regras locais).

**2. A métrica de privacidade não via o texto que o agente recebeu.** No mesmo cenário, a métrica
`sem_dado_pessoal` deu 1,0. O `eval grade` descarta os eventos que só mudam o estado da sessão antes de chamar as
métricas, e é no estado que fica a mensagem recebida. A evidência do mascaramento foi corrigida (afirmava que o
caso do nome provava o SDP). A privacidade passou a ser conferida pelo diário da auditoria
(`tests/eval/conferir_privacidade.py`), em passo próprio do CI que falha se algum dado aparecer; no CI:
*"27 registros conferidos — nenhum dado pessoal no diário"*.

**3. Achado de segurança, na sondagem do gancho de fim de turno.** O `final_cartao` devolvido pelo classificador
entrava sem validação no texto fixo da confirmação ("Bloquear temporariamente o cartão final 1234 meu cpf
[CPF]?"). A execução seguia segura (o executor não achava o cartão), mas o texto que autoriza a transação podia
carregar texto vindo do LLM. Correção em três camadas: formato declarado no catálogo (com invariante no piso),
política que nega parâmetro fora do formato no agente e no executor, e grafo que descarta e pergunta o cartão.

**4. Menores.** `hash` é palavra reservada no SQL do BigQuery (a coluna vai entre crases); no zsh, `$VAR:a`
é modificador de variável (o nome da tabela vai como `${PROJETO}:auditoria.turnos`); uma lista vazia passada
com `destinos or []` virava outra lista, e um destino acrescentado depois não era usado.

## Limites

- A cadeia detecta adulteração, não a impede; quem impede é a retenção travada, e só dentro do prazo.
- Reprocessar registros do diário que não chegaram ao Google Cloud está proposto, não implementado.
- O verificador lê um dia por vez e precisa de leitura no bucket e na tabela (outra identidade, não a do
  agente).
