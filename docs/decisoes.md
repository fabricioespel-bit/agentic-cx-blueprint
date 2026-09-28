# Registro de decisões

Formato curto: **decisão** → alternativa descartada → por quê. Base para ADRs individuais em `docs/adr/`.
Quando uma decisão mudar, atualize esta página.

## Plataforma e modelos

- **Build vs. buy.** Comprar a plataforma (Gemini, Agent Runtime, RAG Engine, Model Armor, provedor de
  WhatsApp) e construir o diferencial (integração transacional, política, guardrails de ação, avaliação).
  → Descartado: suíte de atendimento pronta; construir tudo. → O diferencial está nas regras e no controle
  das ações; padrões abertos nas fronteiras (MCP, OpenTelemetry) reduzem o lock-in.
- **Multimodelo.** Gemini Flash por padrão; Gemini Pro só no agente de conhecimento, por critério (síntese de
  várias fontes, falha na verificação de fundamentação, tema regulatório). → Descartado: Pro para tudo; Flash
  para tudo. → A maioria das mensagens é simples; o critério é validado no conjunto de avaliação. Pro nunca no
  caminho transacional.
- **Orquestração (C1).** ADK no Agent Runtime, com grafo determinístico e LLM dentro dos nós. → Descartado:
  agente autônomo com todas as ferramentas; orquestração própria; LangGraph. → Autonomia onde agrega valor,
  previsibilidade onde não pode haver erro.
- **Residência de dados.** Inferência no endpoint global com texto pseudonimizado, sem dados identificadores
  nem financeiros; sessões, base e auditoria na região. → Descartado: só modelos regionais (a região pode não
  ter os modelos atuais). → O modelo é parâmetro; a opção regional fica disponível por configuração.

## Fluxo agêntico

- **Taxonomia.** Quatro tipos (informação geral, consulta, transação, fora de escopo); escalonamento como saída
  transversal, não como tipo.
- **D1 Roteador.** No gateway, um classificador leve direciona intenções migradas para a camada agêntica e as
  demais para o atendimento existente; aderência por conversa, espelhamento (shadow), canário por intenção e
  kill switch. → Descartado: atendimento existente primeiro, agente como fallback. → Controle da migração por
  configuração; o roteador vira também válvula de capacidade.
- **D2 Dados fora do modelo.** Minimização por desenho, marcadores reversíveis e placeholders. → Descartado:
  só mascarar o que o cliente digita. → Retornos de ferramentas também carregam dados do cliente.
- **D3 Risco assimétrico.** Bloqueio temporário com nível 1 + confirmação; desbloqueio com nível 3, só no app.
  → Descartado: nível 2 sempre. → Atraso no bloqueio causa mais dano que um bloqueio indevido reversível.
- **D4 Confirmação amarrada.** Gerada pela política, texto fixo, vinculada por hash aos parâmetros, uso único,
  validade curta; o executor confere. → Descartado: o LLM pergunta e interpreta o "sim". → Fecha troca de
  parâmetros, reuso de confirmação e pergunta ambígua.
- **D5 Botões.** Confirmação por botão; "sim" digitado só por correspondência exata numa lista fechada. →
  Descartado: LLM interpreta a resposta. → O ponto que autoriza a transação não pode depender de interpretação.
- **D6 Idempotência.** Chave derivada da confirmação, registro de execuções no MCP, consulta de estado antes
  de reexecutar, reconciliação; nunca afirmar sucesso sem confirmação do sistema. → Descartado: confiar na
  idempotência do sistema de origem. → Funciona com legado que não suporta idempotência.
- **D7 Eventos.** Após a execução, evento de negócio no barramento corporativo, com outbox. → Descartado:
  o agente chamar cada sistema. → Desacoplamento e falha isolada.
- **D8 Memória.** Longo prazo só com preferências de interação; fatos nos sistemas de registro. → Descartado:
  memória livre. → Dado desatualizado, escopo de privacidade, erro de extração e envenenamento de memória.
- **Classificador.** Nó de entrada do grafo; pergunta direcionada na ambiguidade; no máximo duas tentativas;
  limite de confiança maior para transações e calibrado na avaliação.

## Containers e componentes

- **N1 Política como serviço (PDP/PEP).** Consultada pelo agente (conversa) e pelo MCP (aplicação).
- **N2 Cofre de sessão.** Armazenamento dedicado, acesso por IAM só do gateway e do MCP; identidade pelo
  contexto autenticado, nunca por parâmetro do LLM. Número de cartão digitado é descartado (fora do escopo PCI).
- **N3 Guardrails em dois pontos.** Mascaramento na região dos dados, no gateway; filtro de injection no agente,
  sobre texto pseudonimizado (permite usar um filtro sem região local sem exposição nova).
- **C2 Roteamento de modelo** no agente de conhecimento, por critério explícito.
- **C3 Escrita só no subfluxo transacional.** O que o LLM não vê, ele não pode ser induzido a usar.
- **C4 Classificador único**, compartilhado entre roteador e agente.
- **MCP por domínio de sistema.** Template do CoE; instâncias por sistema (ex.: cartões), reutilizadas por várias
  áreas. → Descartado: um MCP por área de negócio. → Evita integrações duplicadas.
- **Integrações** pelo gateway de APIs corporativo, com troca de token (o sistema recebe identidade de serviço e
  o cliente como contexto verificado).
- **Local do catálogo no protótipo.** `config/catalogo/`, fora de `app/`. → Se houver deploy no Agent Runtime,
  mover para `app/config/`, porque o pacote de deploy leva só `app/`.

## Segurança e governança

- **K1 Catálogo.** Configuração versionada por área, com segregação de funções, publicada assinada, somente
  leitura em produção; piso de invariantes em código (toda escrita exige confirmação, intenção nova entra em
  shadow, irreversível nunca abaixo do nível 3).
- **G1 Fundamentação.** Citação por afirmação, verificação antes do envio, valores de fonte estruturada,
  documentos com dono e validade.
- **G2 Privacidade.** Minimização, direitos do titular, revisão humana de negativas automáticas, transferência
  internacional restrita a texto pseudonimizado.
- **G3 Auditoria.** Sem identificadores em claro, imutável, acesso restrito, retenção parametrizável.
- **G4 Mudanças.** Tudo versionado, modelo com versão fixada, gate de avaliação, aprovação proporcional ao risco.
- **Cache semântico.** Só informação geral; chave com intenção e entidades; invalidado quando o documento muda;
  só entra o que passou na verificação; na dúvida, não cacheia.

## Avaliação, custo e roadmap

- **Avaliação.** Quatro níveis; métricas por componente; red team com zero escrita ou vazamento; juiz calibrado
  contra humanos; recontato em 24–72h como métrica de resolução.
- **Custo.** Conversas de conhecimento custam várias vezes mais que transações; alavancas: cache semântico,
  cache de contexto, modelo menor no classificador, limite de turnos, avaliações em lote.
- **Roadmap.** Promoção por intenção (fundação → shadow → assistido → autônomo em conhecimento → autônomo em
  transações), critérios definidos antes, regressão automática em violação de segurança.
