# agentic-cx-blueprint

Blueprint de um **assistente agêntico para atendimento bancário** (WhatsApp e app): responde com base no
conhecimento oficial do banco e executa transações simples, com uma tese central:
**o LLM interpreta, a regra autoriza.**

O banco é fictício (**Banco Exemplo**), e todos os dados são inventados.

> **Status:** em construção. A arquitetura de referência está completa; o protótipo começa pelo núcleo
> determinístico (política, confirmação amarrada aos parâmetros, idempotência). Veja o que já está implementado
> em [docs/arquitetura.md](docs/arquitetura.md#implementado--proposto).

## Documentação

- [Arquitetura de referência](docs/arquitetura.md): C4 (contexto, containers, componentes), fluxos, segurança,
  avaliação e implantação.
- [Registro de decisões](docs/decisoes.md): cada decisão com a alternativa descartada e o porquê.
- [Plano do protótipo](docs/plano-prototipo.md): fases e critério de pronto.

## Stack

Google ADK · Gemini (Flash e Pro) · Agent Runtime · RAG Engine · MCP · Model Armor · Firestore · Cloud Run ·
OpenTelemetry. Projeto criado com agents-cli (`uv tool install google-agents-cli`).

## Como rodar

Requer [uv](https://docs.astral.sh/uv/), agents-cli e Google Cloud SDK autenticado.

```bash
cp .env.example .env        # ajuste GOOGLE_CLOUD_PROJECT
agents-cli install
uv run pytest tests/unit    # testes do núcleo determinístico (sem LLM)
agents-cli playground       # conversa interativa com o agente
```
