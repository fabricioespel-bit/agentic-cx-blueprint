# agentic-cx-blueprint

[![testes](https://github.com/fabricioespel-bit/agentic-cx-blueprint/actions/workflows/testes.yml/badge.svg)](https://github.com/fabricioespel-bit/agentic-cx-blueprint/actions/workflows/testes.yml)

Blueprint de um **assistente agêntico para atendimento bancário** (WhatsApp e app): responde com base no
conhecimento oficial do banco e executa transações simples, com uma tese central:
**o LLM interpreta, a regra autoriza.**

O banco é fictício (**Banco Exemplo**), e todos os dados são inventados.

## O que roda hoje

O **agente funciona de ponta a ponta** para cartões: bloqueio (com escolha do cartão e confirmação), consulta
de limite e lista de cartões, com negações em texto fixo (desbloqueio só no app, fora de escopo, intenção
desconhecida). É um grafo do ADK em que, **nas transações, o LLM só classifica a mensagem**; rotas, chamadas ao servidor MCP,
confirmação e respostas são código. Num bloqueio de três turnos, o Gemini é chamado uma vez
([evidência no playground](docs/evidencias/playground-2026-09-29.md)).

Também **responde dúvidas sobre cartões e tarifas** com citação da fonte. O LLM redige a partir dos trechos
encontrados, mas **nunca escreve um número**: valores aparecem como marcadores (`{{anuidade_classico}}`), o
código verifica a resposta (fonte recuperada, valor presente no trecho citado, nenhum número solto) e só então
preenche os valores da tabela oficial. Sem fonte que responda, o agente recusa e oferece atendimento
([evidência no playground, com um achado e sua correção](docs/evidencias/playground-2026-10-01.md)).

Por baixo dele, o **núcleo determinístico**, testado sem LLM, decide se uma ação pode ser executada, com quais
parâmetros e com qual autenticação.

| Peça | O que garante | Código |
|---|---|---|
| Catálogo de intenções | Negação por padrão; piso de invariantes que nenhuma configuração sobrescreve (toda escrita exige confirmação, irreversível exige nível 3, intenção nova entra em shadow) | `config/catalogo/`, `app/nucleo/catalogo.py` |
| Política | Consultada pelo agente e pelo executor, e vale a do executor; checa canal, nível de autenticação e limite diário | `app/nucleo/politica.py` |
| Confirmação amarrada | Texto fixo do catálogo, hash de sessão + intenção + parâmetros, uso único, validade curta | `app/nucleo/confirmacao.py` |
| Registro de execuções | Idempotência técnica (mesma confirmação executa uma vez); timeout vira consulta de estado, nunca sucesso presumido; reconciliação | `app/nucleo/execucoes.py` |
| Servidor MCP de cartões | Protocolo MCP real (SDK 1.x); identidade e confirmação fora do schema que o LLM vê; idempotência de negócio (bloquear cartão já bloqueado é recusado, sem nova execução) | `app/mcp_cartoes/` |
| Agente (grafo do ADK) | LLM só em nós sem ferramentas (classificador; redator e revisor no conhecimento); respostas que autorizam ("1234", "SIM") nunca passam pelo LLM; a escrita só é alcançável depois da confirmação | `app/agent.py`, `app/orquestrador/` |
| Conhecimento | Corpus com dono e vigência, sem números no texto; busca; verificação de fundamentação; valores preenchidos pelo código; no máximo uma revisão (Gemini Pro) antes da recusa | `config/conhecimento/`, `app/conhecimento/` |

**Mock, e dito assim no código:** sistema de cartões, cofre de sessão e armazenamentos ficam em memória; o
catálogo não é assinado; a busca é lexical e local, e a tabela de valores é um arquivo. **Adequações do
protótipo:** confirmação por "SIM" digitado (em produção, botão do canal), sessão de demonstração (em
produção, aberta pelo gateway), servidor MCP no mesmo processo. **Ainda não implementado:** busca semântica
(RAG Engine), mascaramento de dados antes do LLM, avaliação contínua no CI e observabilidade. O status
completo está na tabela
[Implementado × proposto](docs/arquitetura.md#implementado--proposto).

## Documentação

- [Arquitetura de referência](docs/arquitetura.md): C4 (contexto, containers, componentes), fluxos, segurança,
  avaliação e implantação.
- [Registro de decisões](docs/decisoes.md): cada decisão com a alternativa descartada e o porquê.
- [Plano do protótipo](docs/plano-prototipo.md): fases e critério de pronto.

## Como rodar os testes

Requer [uv](https://docs.astral.sh/uv/). Não precisa de conta no Google Cloud.

```bash
uv sync
uv run pytest tests/unit -q
```

Os testes do núcleo cobrem, entre outros: intenção fora do catálogo negada, escrita sem confirmação negada,
confirmação com parâmetros trocados, expirada ou reutilizada negada, nível de autenticação insuficiente,
canal não permitido, limite diário, mesma confirmação executando uma única vez e timeout seguido de consulta
de estado. Os testes do servidor MCP usam um cliente MCP real, conectado em memória. Os testes do agente
rodam conversas completas pelo grafo com classificador e redatores falsos, sem LLM. Os de conhecimento
cobrem a validação do corpus (número fora de marcador, chave fora da tabela, vigência), a calibração da
busca e cada regra da verificação (fonte fora da busca, valor de outro trecho, número solto).

## Como avaliar com o modelo real

Os testes acima usam LLM falso. A avaliação roda o agente de verdade sobre 23 perguntas (resposta, recusa,
lacuna conhecida, manipulação e roteamento) e mede comportamento, conteúdo, custo e fidelidade, esta com um
juiz LLM calibrado contra rótulos humanos. Encontrou três defeitos, corrigidos e medidos em três rodadas
([evidência](docs/evidencias/avaliacao-2026-10-05.md)).

```bash
uv run uvicorn app.fast_api_app:app --host 127.0.0.1 --port 18080      # em outro terminal
agents-cli eval run --url http://127.0.0.1:18080 --app-name app \
  --dataset tests/eval/datasets/conhecimento.json --config tests/eval/eval_config.yaml
```

## Como conversar com o agente

Requer, além do uv, o [agents-cli](https://pypi.org/project/google-agents-cli/) e um projeto do Google Cloud
com Vertex AI (o classificador e, nas dúvidas, o redator chamam o Gemini; cada mensagem custa uma fração de
centavo).

```bash
cp .env.example .env        # ajuste GOOGLE_CLOUD_PROJECT
agents-cli playground
```

Roteiro: "perdi minha carteira, preciso bloquear meu cartão" → "1234" → "SIM". Depois, "quero desbloquear
meu cartão", "qual ação devo comprar?", "qual a anuidade do cartão Clássico?" e "o cartão Platinum dá
cashback?" (não está na base: o agente recusa).

## Stack

Google ADK · Gemini (Flash e Pro) · Agent Runtime · RAG Engine · MCP · Model Armor · Firestore · Cloud Run ·
OpenTelemetry. Projeto criado com agents-cli (`uv tool install google-agents-cli`). No protótipo, até aqui:
Python, Pydantic, SDK MCP e pytest.