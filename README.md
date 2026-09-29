# agentic-cx-blueprint

[![testes](https://github.com/fabricioespel-bit/agentic-cx-blueprint/actions/workflows/testes.yml/badge.svg)](https://github.com/fabricioespel-bit/agentic-cx-blueprint/actions/workflows/testes.yml)

Blueprint de um **assistente agêntico para atendimento bancário** (WhatsApp e app): responde com base no
conhecimento oficial do banco e executa transações simples, com uma tese central:
**o LLM interpreta, a regra autoriza.**

O banco é fictício (**Banco Exemplo**), e todos os dados são inventados.

## O que roda hoje

O **agente funciona de ponta a ponta** para cartões: bloqueio (com escolha do cartão e confirmação), consulta
de limite e lista de cartões, com negações em texto fixo (desbloqueio só no app, fora de escopo, intenção
desconhecida). É um grafo do ADK em que **o LLM só classifica a mensagem**; rotas, chamadas ao servidor MCP,
confirmação e respostas são código. Num bloqueio de três turnos, o Gemini é chamado uma vez
([evidência no playground](docs/evidencias/playground-2026-09-29.md)).

Por baixo dele, o **núcleo determinístico**, testado sem LLM, decide se uma ação pode ser executada, com quais
parâmetros e com qual autenticação.

| Peça | O que garante | Código |
|---|---|---|
| Catálogo de intenções | Negação por padrão; piso de invariantes que nenhuma configuração sobrescreve (toda escrita exige confirmação, irreversível exige nível 3, intenção nova entra em shadow) | `config/catalogo/`, `app/nucleo/catalogo.py` |
| Política | Consultada pelo agente e pelo executor, e vale a do executor; checa canal, nível de autenticação e limite diário | `app/nucleo/politica.py` |
| Confirmação amarrada | Texto fixo do catálogo, hash de sessão + intenção + parâmetros, uso único, validade curta | `app/nucleo/confirmacao.py` |
| Registro de execuções | Idempotência (mesma confirmação executa uma vez); timeout vira consulta de estado, nunca sucesso presumido; reconciliação | `app/nucleo/execucoes.py` |
| Servidor MCP de cartões | Protocolo MCP real (SDK 1.x); identidade e confirmação fora do schema que o LLM vê | `app/mcp_cartoes/` |
| Agente (grafo do ADK) | LLM só no classificador, sem ferramentas; respostas que autorizam ("1234", "SIM") nunca passam pelo LLM; a escrita só é alcançável depois da confirmação | `app/agent.py`, `app/orquestrador/` |

**Mock, e dito assim no código:** sistema de cartões, cofre de sessão e armazenamentos ficam em memória; o
catálogo não é assinado. **Adequações do protótipo:** confirmação por "SIM" digitado (em produção, botão do
canal), sessão de demonstração (em produção, aberta pelo gateway), servidor MCP no mesmo processo. **Ainda
não implementado:** base de conhecimento (dúvidas de produto recebem um texto fixo), mascaramento de dados
antes do LLM, avaliação e observabilidade. O status completo está na tabela
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
rodam conversas completas pelo grafo com um classificador falso, sem LLM.

## Como conversar com o agente

Requer, além do uv, o [agents-cli](https://pypi.org/project/google-agents-cli/) e um projeto do Google Cloud
com Vertex AI (o classificador chama o Gemini; cada mensagem nova custa uma fração de centavo).

```bash
cp .env.example .env        # ajuste GOOGLE_CLOUD_PROJECT
agents-cli playground
```

Roteiro: "perdi minha carteira, preciso bloquear meu cartão" → "1234" → "SIM". Depois, "quero desbloquear
meu cartão" e "qual ação devo comprar?".

## Stack

Google ADK · Gemini (Flash e Pro) · Agent Runtime · RAG Engine · MCP · Model Armor · Firestore · Cloud Run ·
OpenTelemetry. Projeto criado com agents-cli (`uv tool install google-agents-cli`). No protótipo, até aqui:
Python, Pydantic, SDK MCP e pytest.