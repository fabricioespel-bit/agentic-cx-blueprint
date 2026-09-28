# Plano do protótipo

Objetivo: tornar executável o núcleo da [arquitetura](arquitetura.md), começando pelo que mais sustenta a tese
"o LLM interpreta, a regra autoriza": a camada determinística de política, confirmação e execução.

## Premissas

- Banco fictício (**Banco Exemplo**); todos os dados, produtos e documentos são inventados.
- Sistemas do banco são **mocks** explícitos (servidor MCP de cartões com estado em memória ou arquivo).
- Modelos: `gemini-3.8-flash` (padrão, endpoint global) e `gemini-2.5-pro` (por critério).
- Região dos serviços: `southamerica-east1` (Agent Runtime e RAG Engine disponíveis na região).

## Fases

| Fase | Entrega | Prioridade |
|---|---|---|
| **P1. Base** | Corpus fictício (produtos, tarifas, políticas); catálogo de intenções em YAML com esquema e validação; ajuste de região no scaffold | Agora |
| **P2. Núcleo determinístico** | Serviço de política + piso de invariantes; confirmação amarrada aos parâmetros (hash, uso único, validade); registro de execuções com idempotência; servidor MCP de cartões (mock) com leitura/escrita separadas e identidade pelo contexto; **testes unitários** de tudo | Agora |
| P3. Conhecimento | RAG Engine com o corpus; citação; verificação de fundamentação; valores da tabela oficial por ferramenta | Em seguida |
| P4. Guardrails e auditoria | Mascaramento, Model Armor como plugin, trilha de auditoria, escalonamento com resumo | Em seguida |
| P5. Avaliação | Golden set, red team, juiz, gate | Em seguida |
| P6. Observabilidade e custo | Traces OpenTelemetry, custo e latência medidos por conversa | Em seguida |
| P7. Demo e deploy | Playground/demo web; deploy no Agent Runtime (**só com aprovação explícita**) | Opcional |

## Critério de pronto do núcleo (P2)

- `uv run pytest tests/unit` passando, cobrindo: intenção fora do catálogo negada; escrita sem confirmação
  negada; confirmação com parâmetros diferentes negada; confirmação expirada ou reutilizada negada; nível de
  autenticação insuficiente negado; limite por canal; execução repetida com a mesma chave executa uma vez;
  timeout seguido de consulta de estado.
- Nenhum teste de pytest verifica conteúdo gerado por LLM (isso é avaliação, fase P5).

## Verificação

- Testes unitários do núcleo, sem LLM.
- `agents-cli run` para smoke test do agente depois da integração com o núcleo.
- A tabela "Implementado × proposto" da arquitetura é atualizada a cada fase concluída.
