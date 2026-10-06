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
- **Texto de confirmação no catálogo.** Cada transação tem texto fixo na configuração; o piso recusa
  transação sem ele. → Descartado: o agente redigir a pergunta. → O ponto que autoriza não depende de texto
  gerado pelo LLM.
- **Confirmação consumida em qualquer tentativa.** Tentativa com parâmetros, sessão ou intenção divergentes
  inutiliza a confirmação. → Descartado: permitir nova tentativa com a mesma confirmação. → Quem tenta
  trocar parâmetros perde a confirmação; o cliente legítimo só confirma de novo.

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
- **SDK MCP 1.x.** → Descartado: 2.x. → O ADK 2.8 exige `mcp<2`; o `McpToolset` do agente usa a API 1.x.
- **Identidade e confirmação no `_meta` da requisição MCP.** → Descartado: parâmetros da ferramenta. →
  Ficam fora do schema que o LLM vê; em produção, o token vem no header HTTP autenticado.
- **Retomada de execução incerta sem nova confirmação.** Mesma chave, mesmos dados: consulta o estado e,
  se não aplicado, reexecuta. → Descartado: pedir nova confirmação. → A autorização já foi dada para aquela
  chave exata; bloqueio atrasado custa mais que um bloqueio reexecutado.
- **Limite diário conta execuções pendentes e incertas.** → Descartado: contar só as concluídas. → Na
  dúvida, a execução pode ter acontecido.
- **Agente como grafo (`Workflow` do ADK) com o LLM em nós sem ferramentas.** O classificador e os redatores de
  conhecimento têm saída estruturada, temperatura 0 e nenhuma ferramenta; rotas, chamadas ao MCP, verificação
  e respostas são código. → Descartado: `Agent` com as ferramentas do MCP. → A escrita só é alcançável pelo nó
  de execução, depois de uma confirmação comparada por código; não há caminho do LLM até ela.
- **Conversa de vários turnos por estado da sessão.** Pendência de escolha de cartão ou de confirmação fica no
  estado; com pendência, a mensagem vai direto ao código, sem LLM. → Descartado: HITL (`RequestInput`) do
  ADK. → Funciona igual em qualquer canal de texto e não depende de suporte da interface.
- **Pré-check antes de pedir dados.** `Politica.verificar` nega pela intenção e pelo contexto antes de
  perguntar o cartão. → Descartado: só avaliar com parâmetros completos. → Não pedir ao cliente um dado que
  não vai ser usado.
- **Idempotência de negócio.** Pedido sem efeito (bloquear cartão já bloqueado) é recusado no executor, pela
  situação no sistema de origem, sem abrir execução, gerar protocolo ou contar no limite diário; o agente
  consulta a situação antes de pedir confirmação e responde com texto fixo. → Descartado: só a idempotência
  técnica (mesma confirmação executa uma vez). → Não afirmar ação que não aconteceu; o cartão pode ter sido
  bloqueado por outro canal, que o registro de execuções não conhece.
- **Adequações do protótipo no canal.** Confirmação por "SIM" digitado com correspondência exata (a D5 prevê
  isso como alternativa; em produção, botão do WhatsApp ou do app, cujo id carrega a confirmação); sessão de
  demonstração aberta no primeiro turno (em produção, pelo gateway); servidor MCP no mesmo processo, com
  transporte em memória (em produção, Cloud Run com HTTP autenticado e estado no Firestore).
- **Local do catálogo no protótipo.** `config/catalogo/`, fora de `app/`. → Se houver deploy no Agent Runtime,
  mover para `app/config/`, porque o pacote de deploy leva só `app/`.

## Conhecimento

- **Números só na tabela oficial.** Documentos citam valores por marcador (`{{chave}}`) e não têm dígitos; o
  código preenche e formata depois da verificação. → Descartado: valores no texto dos documentos. → O LLM não
  tem de onde copiar um número; reajuste de tarifa vale sem reeditar documento nem reindexar.
- **Autoria e publicação em produção.** Autores escrevem em Word numa biblioteca do SharePoint, com metadados
  (dono, vigência) e fluxo de aprovação; um pipeline próprio converte, valida com as regras de
  `app/conhecimento/corpus.py` (metadados, vigência, marcadores, número solto), divide por seção e publica no
  RAG Engine, devolvendo ao autor os problemas em linguagem simples. Valores vêm do sistema de produtos e
  tarifas por ferramenta de leitura. → Descartado: conector direto da biblioteca ao RAG Engine. → O conector
  importa sem validar; o pipeline é o ponto de controle. No protótipo, `config/conhecimento/` simula o
  conteúdo publicado.
- **Trecho = seção do documento.** Divisão pelos títulos `##`, com id estável (`documento#secao`); regra e
  exceção ficam na mesma seção. → Descartado: divisão por tamanho. → A citação aponta para o que o autor
  escreveu, e a exceção não se separa da regra.
- **Busca atrás de uma interface; lexical local no protótipo.** `Buscador`, com `BuscadorLocal` (IDF, peso no
  título da seção, corte mínimo e relativo ao melhor trecho) e o RAG Engine como adaptador. → Descartado: RAG
  Engine desde o início. → Testes determinísticos e sem custo fixo. Na calibração, prefere não achar a achar
  errado (redução por prefixo descartada: "tempo" casava com "temporário").
- **Verificação de fundamentação em código.** Toda afirmação cita trecho recuperado nesta busca; todo marcador
  está num trecho citado pela afirmação; nenhum número fora de marcador. → Descartado: confiar no prompt; juiz
  LLM no caminho da resposta. → Determinística e testável. Garante procedência, não relevância, que fica para
  a avaliação (P5).
- **Fontes normalizadas antes da verificação.** Colchetes e espaços nas pontas do id citado saem; o id ainda
  precisa ser um trecho recuperado. → Descartado: recusar o id com colchetes. → Erro de forma não deve virar
  recusa ao cliente; na avaliação, o redator copiou "[id]" e o revisor repetiu o erro
  ([evidência](evidencias/escalonamento-2026-10-06.md)).
- **Redator e revisor como nós separados.** Redator (Flash) e, se a verificação reprova uma resposta com
  conteúdo, revisor (Pro) com os problemas encontrados; segunda reprovação vira recusa com texto fixo. →
  Descartado: laço de tentativas num nó só. → Sem ciclo no grafo, o limite de chamadas é estrutural (até três
  por turno, com o classificador); o Pro entra só onde a decisão de multimodelo prevê.
- **Recusa do redator não vai ao revisor.** Lista vazia de afirmações é recusa honesta e vira "não encontrei;
  quer falar com um atendente?". → Descartado: tratar como falha a revisar. → No playground, o revisor
  pressionado a corrigir respondeu fora do tema com conteúdo das fontes
  ([evidência](evidencias/playground-2026-10-01.md)).
- **Só nós de código entregam mensagem ao cliente.** Saídas de LLM (classificador, redator, revisor) ficam nos
  eventos da sessão; o canal entrega apenas as mensagens dos nós de resposta, montadas por código depois da
  verificação. → Descartado: o canal repassar tudo que o agente emite. → Texto não verificado nunca chega ao
  cliente. No playground (ADK web), essas saídas aparecem por ser ferramenta de desenvolvimento.
- **Instrução do redator por função.** → Descartado: instrução em texto. → O ADK aplica template de estado a
  instruções em texto e leria `{{chave}}` como variável de sessão.
- **Vigência pela data de São Paulo.** → Descartado: data em UTC. → Documento vigente a partir do dia 1º
  valeria às 21h da véspera.

## Guardrails

- **Mascaramento com o Sensitive Data Protection regional e regras locais juntos.** O SDP é chamado no
  endpoint de `southamerica-east1` (o texto real não sai da região); regras com dígito verificador para CPF
  (cálculo do CPF) e cartão (Luhn) rodam sempre. → Descartado: só regras locais; só o SDP. → O SDP detecta nome
  e endereço, que regras não pegam; as regras são a segunda camada para os dados mais graves e a contingência.
- **Se o SDP falhar, seguem as regras locais.** A falha é registrada sem o texto. → Descartado: recusar a
  mensagem. → CPF, cartão, e-mail e telefone continuam cobertos, e o cliente não fica sem atendimento quando
  o serviço oscila.
- **Limite de confiança "possível".** → Descartado: "provável" ou acima. → Na sondagem, cartão sem espaços e
  nome completo só apareceram nesse nível; nenhum falso positivo em "final 1234", valores e datas. Primeiro
  nome isolado não é detectado (limitação aceita: identifica pouco).
- **Mascaramento como plugin do ADK, alterando a própria mensagem.** `on_user_message_callback` roda antes da
  sessão e do grafo, no papel do gateway. → Descartado: devolver uma mensagem nova. → O runner guarda a
  mensagem original como entrada do grafo antes do callback: a sessão ficaria mascarada e o classificador
  receberia o texto original (provado em teste). Um teste também garante que o método sobrescreve o gancho.
- **Número completo de cartão vira aviso fixo, sem LLM.** O marcador `[NUMERO_DE_CARTAO]` faz a entrada do
  grafo responder e cancelar qualquer pendência. → Descartado: classificar a mensagem mascarada. → Fora do
  escopo PCI; nada a interpretar, e nenhuma chamada ao modelo.

- **Formato declarado para todo parâmetro interpolado na confirmação.** O catálogo declara uma expressão
  regular por parâmetro; o piso recusa texto de confirmação com campo sem formato; agente e executor negam
  parâmetro fora do formato, faltando ou sobrando; o grafo descarta final de cartão fora do formato e pergunta.
  → Descartado: confiar na instrução do classificador. → Sem a regra, uma saída do LLM chegava ao texto que
  autoriza a transação.

## Auditoria

- **Um registro por turno, sem dado pessoal em claro.** Mensagem já mascarada, cliente pelo pseudônimo,
  intenção, motivo, execução, fontes, nós com LLM e resposta. → Descartado: registrar os eventos brutos da
  sessão. → Os eventos têm saídas de LLM não verificadas e não dizem por que o agente decidiu.
- **Resumo do turno no estado, marcado pelos nós.** Só o que não se lê na resposta (intenção, motivo, final
  descartado, execução); o desfecho é reconhecido pelos textos fixos. → Descartado: o plugin interpretar os
  eventos. → Nós de código aparecem nos eventos com o nome do grafo; o resumo é explícito e testável.
- **Cadeia de hashes por sessão.** Cada registro leva o hash do anterior da mesma sessão; o elo fica no estado.
  → Descartado: cadeia global. → Instâncias em paralelo não precisam se coordenar. A cadeia detecta
  adulteração, não a impede.
- **Registro completo no Cloud Storage com retenção travada; só metadados no BigQuery.** → Descartado: tudo no
  BigQuery; retenção sem trava. → O bucket impede alterar e apagar dentro do prazo, até para o dono do projeto
  (testado); a tabela consultável fica sem o texto das conversas (minimização). Objeto gravado só se não
  existir (`if_generation_match=0`).
- **Quem grava não lê.** A conta do agente tem só `storage.objectCreator` no bucket e `bigquery.dataEditor`
  na tabela. → Descartado: papéis amplos no projeto. → Separação de funções: a auditoria é lida por outra
  identidade (o verificador).
- **Diário local antes do envio, envio em segundo plano.** → Descartado: gravar no Google Cloud dentro do turno;
  descartar o registro se o envio falhar. → A resposta não espera dois serviços, e uma falha de envio não perde
  o registro. Reprocessamento do diário fica proposto.
- **O agente carrega o `.env` e registra as proteções ativas na partida.** → Descartado: depender do
  `fast_api_app.py`. → O pacote `app` importa o agente antes; localmente, o agente subia sem SDP e sem auditoria
  no Google Cloud, sem aviso ([evidência](evidencias/auditoria-2026-10-06.md)).
- **Privacidade da avaliação conferida pelo diário da auditoria.** → Descartado: só a métrica
  `sem_dado_pessoal`. → O `eval grade` descarta os eventos de estado; a métrica não vê o texto que o agente
  recebeu. O diário registra exatamente esse texto.

## Escalonamento

- **Pedido de atendente num campo próprio do classificador.** `pede_atendente`, ao lado da intenção. →
  Descartado: uma intenção "falar com atendente" no catálogo. → Escalonamento é saída transversal, não tipo
  (Taxonomia); "não consigo bloquear, me passa para alguém" tem as duas coisas, e as duas ficam registradas.
- **Aceite da oferta só por "sim", comparado por código.** Textos que oferecem atendente deixam uma pendência;
  outra resposta derruba a oferta e segue o caminho normal. → Descartado: o LLM interpretar o aceite. → O mesmo
  critério da confirmação (D5), e o cliente não fica preso à oferta.
- **Três falhas seguidas encaminham sozinhas.** Negado, falha, sem fonte, cartão não encontrado e confirmação
  inválida contam; fora de escopo não. → Descartado: esperar o cliente pedir. → Insistir com quem não está sendo
  atendido é a experiência que o escalonamento existe para evitar.
- **Resumo para o atendente montado por código, a partir do histórico da auditoria.** → Descartado: resumo
  gerado por LLM. → O atendente age com base nele; gerado da trilha, só contém o que o agente registrou, já
  mascarado.
- **Depois do encaminhamento, o agente não responde por cima.** Novas mensagens recebem o protocolo, sem LLM.
  → Descartado: seguir atendendo até o humano assumir. → Duas vozes na mesma conversa confundem o cliente.

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
- **Métricas de código onde o resultado é verificável; juiz LLM só para interpretar texto.** Comportamento,
  valores, fontes e chamadas ao modelo são conferidos por código contra o esperado de cada caso; o juiz julga
  apenas o texto diante dos trechos citados. → Descartado: juiz para tudo; métricas prontas do serviço. → O que
  é verificável não depende de outro LLM; a rota `/app-info` do ADK não descreve um `Workflow`, e as métricas
  prontas perdem contexto.
- **Recusa indevida medida pela métrica de código, não pelo juiz.** → Descartado: juiz com o corpus inteiro. → O
  dataset sabe o que o corpus contém; o juiz, que vê só os trechos citados, não tem como saber.
- **Juiz em modelo diferente do redator, calibrado contra rótulos humanos.** `gemini-2.5-pro`, temperatura 0;
  concordância medida antes de usar, divergências adjudicadas e registradas, validação em respostas que não
  serviram ao ajuste. → Descartado: confiar no juiz sem calibração. → Uma métrica não validada pode premiar o
  erro; na calibração, ele acertou os dois casos `incompleto` com o motivo certo.
- **Escala de gravidade com nota parcial.** `ok` 1, `excesso` 0,5, `incompleto`, `nao_responde` e `infiel` 0;
  `excesso` é outra situação além da perguntada, não detalhe da mesma. → Descartado: aprovado ou reprovado. →
  "Aceitável, mas não ideal" não deve pesar como erro; a primeira definição de excesso gerou falso positivo.
- **Lacunas conhecidas mantidas no conjunto, falhando.** → Descartado: tirar os casos ou aceitar a recusa. →
  Rebaixar o critério esconde o problema; são os casos de comparação para a busca semântica.
- **Avaliação contra o servidor já rodando.** `eval run --url`. → Descartado: deixar o agents-cli subir o
  servidor. → Ele espera 30 s, e o agente leva cerca de 80 s para subir nesta máquina.
- **Avaliação no CI com federação de identidade.** O GitHub Actions troca um token OIDC de curta duração por
  credencial temporária de uma conta de serviço que só chama a Vertex AI; o provedor aceita apenas o id deste
  repositório e o branch `main`, e a permissão na conta de serviço repete a restrição pelo id. → Descartado:
  chave JSON da conta de serviço como segredo; condição pelo nome do repositório. → Sem segredo para vazar; o id
  não muda se o repositório for apagado e recriado com o mesmo nome. Papel `roles/aiplatform.user` (pronto,
  mais amplo que o necessário; papel customizado só com predição fica como melhoria). Gatilhos só no `main` e
  manuais, nunca em PR; uma execução por vez; orçamento mensal que avisa (não bloqueia).
- **Avaliação informativa antes de virar gate.** → Descartado: bloquear o merge desde a primeira execução. →
  Notas de LLM oscilam; o gate vem depois de execuções estáveis e de casos com problema no conjunto.
- **Custo.** Conversas de conhecimento custam várias vezes mais que transações; alavancas: cache semântico,
  cache de contexto, modelo menor no classificador, limite de turnos, avaliações em lote.
- **Roadmap.** Promoção por intenção (fundação → shadow → assistido → autônomo em conhecimento → autônomo em
  transações), critérios definidos antes, regressão automática em violação de segurança.
