# Plano do protótipo

Objetivo: tornar executável o núcleo da [arquitetura](arquitetura.md), começando pelo que mais sustenta a tese
"o LLM interpreta, a regra autoriza": a camada determinística de política, confirmação e execução.

## Premissas

- Banco fictício (**Banco Exemplo**); todos os dados, produtos e documentos são inventados.
- Sistemas do banco são **mocks** explícitos (servidor MCP de cartões com estado em memória ou arquivo).
- Modelos: `gemini-3.8-flash` (padrão, endpoint global) e `gemini-2.5-pro` (por critério).
- Região dos serviços: `southamerica-east1` (Agent Runtime e RAG Engine disponíveis na região).

## Fases

| Fase | Entrega | Situação |
|---|---|---|
| **P1. Base** | Corpus fictício (produtos, tarifas, políticas); catálogo de intenções em YAML com esquema e validação; ajuste de região no scaffold | Feita (o corpus entrou na P3) |
| **P2. Núcleo determinístico** | Serviço de política + piso de invariantes; confirmação amarrada aos parâmetros (hash, uso único, validade); registro de execuções com idempotência; servidor MCP de cartões (mock) com leitura/escrita separadas e identidade pelo contexto; **testes unitários** de tudo | Feita |
| **P3. Conhecimento** | Corpus com dono e vigência; busca; citação por afirmação; verificação de fundamentação; valores da tabela oficial; RAG Engine como adaptador de busca | Feita, exceto o RAG Engine (P3.6) |
| **P4. Guardrails e auditoria** | Mascaramento, Model Armor, trilha de auditoria, escalonamento com resumo | Feita (o Model Armor entrou no grafo, não como plugin; ver decisões) |
| **P5. Avaliação** | Golden set, red team, juiz, gate | Em andamento: conjunto de casos, métricas, juiz calibrado e avaliação no CI (federação de identidade) feitos; red team ampliado, comparação de temperatura e gate pendentes |
| **P6. Observabilidade e custo** | Traces OpenTelemetry, custo e latência medidos por conversa | Feita (traces sem o texto da conversa; custo só do LLM; coletor, métricas e alertas propostos). Próximo passo indicado pelos números: latência (limitar o pensamento, revisar prazos) |
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
