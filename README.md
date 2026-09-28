# agentic-cx-blueprint

[![testes](https://github.com/fabricioespel-bit/agentic-cx-blueprint/actions/workflows/testes.yml/badge.svg)](https://github.com/fabricioespel-bit/agentic-cx-blueprint/actions/workflows/testes.yml)

Blueprint de um **assistente agêntico para atendimento bancário** (WhatsApp e app): responde com base no
conhecimento oficial do banco e executa transações simples, com uma tese central:
**o LLM interpreta, a regra autoriza.**

O banco é fictício (**Banco Exemplo**), e todos os dados são inventados.

## O que roda hoje

O **núcleo determinístico** está implementado e testado, sem LLM: é a parte que decide se uma ação pode ser
executada, com quais parâmetros e com qual autenticação.

| Peça | O que garante | Código |
|---|---|---|
| Catálogo de intenções | Negação por padrão; piso de invariantes que nenhuma configuração sobrescreve (toda escrita exige confirmação, irreversível exige nível 3, intenção nova entra em shadow) | `config/catalogo/`, `app/nucleo/catalogo.py` |
| Política | Consultada pelo agente e pelo executor, e vale a do executor; checa canal, nível de autenticação e limite diário | `app/nucleo/politica.py` |
| Confirmação amarrada | Texto fixo do catálogo, hash de sessão + intenção + parâmetros, uso único, validade curta | `app/nucleo/confirmacao.py` |
| Registro de execuções | Idempotência (mesma confirmação executa uma vez); timeout vira consulta de estado, nunca sucesso presumido; reconciliação | `app/nucleo/execucoes.py` |
| Servidor MCP de cartões | Protocolo MCP real (SDK 1.x); identidade e confirmação fora do schema que o LLM vê | `app/mcp_cartoes/` |

**Mock, e dito assim no código:** sistema de cartões, cofre de sessão e armazenamentos ficam em memória; o
catálogo não é assinado. **Ainda não integrado:** o agente em `app/agent.py` ainda é o template do scaffold;
a ligação com o núcleo é a próxima etapa. O status completo está na tabela
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
de estado. Os testes do servidor MCP usam um cliente MCP real, conectado em memória.

## Stack

Google ADK · Gemini (Flash e Pro) · Agent Runtime · RAG Engine · MCP · Model Armor · Firestore · Cloud Run ·
OpenTelemetry. Projeto criado com agents-cli (`uv tool install google-agents-cli`). No protótipo, até aqui:
Python, Pydantic, SDK MCP e pytest.

O que mudou em relação ao README atual, e por quê:
- Badge do CI: quem abre o repo vê na hora que os testes passam.
- "O que roda hoje" em vez de "em construção": diz o que existe, com o código de cada peça e o que cada uma garante.
- Tirei o agents-cli playground do "Como rodar". Hoje ele subiria o agente de clima do template, e isso seria overclaim. Ele volta quando fizermos a integração do agente (item A).
- Sem GCP para rodar os testes. Removi o cp .env.example e o agents-cli install, que não são necessários para o que roda hoje. Qualquer pessoa consegue reproduzir só com o uv.
- Limites explícitos: o que é mock e o que ainda não está integrado, seguindo a regra do projeto de não fazer overclaim.