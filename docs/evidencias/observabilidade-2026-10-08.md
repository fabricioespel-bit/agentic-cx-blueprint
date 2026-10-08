# Evidência: observabilidade e custo (7 e 8/out/2026)

O P6 mede cada turno sem copiar o texto da conversa para fora da trilha de auditoria. São três peças: o uso por
turno na própria trilha (P6.1), traces só com metadados (P6.2) e custo e latência calculados a partir do uso
(P6.3). Dados fictícios; os números vêm das avaliações no CI e de testes locais.

## Onde fica cada dado

| | Trilha de auditoria | Traces |
|---|---|---|
| Onde | diário, Cloud Storage com retenção travada, BigQuery (southamerica-east1) | Cloud Trace (bucket em `us`) |
| Texto da mensagem e da resposta | sim, já mascarado | **não** |
| Uso | duração do turno; por chamada ao LLM: nó, modelo, duração, tokens | duração de cada etapa, tokens |
| Identificação | `cliente_ref`, sessão | só ids aleatórios de sessão e invocação |
| Para que serve | análise agregada: latência, custo, por intenção, ao longo do tempo | investigar um turno: onde foi o tempo |

O registro de auditoria guarda o `trace_id` do turno (versão 3 do registro): é por ele que se vai de um turno
lento no relatório ao trace que mostra a etapa responsável.

## Traces sem o texto da conversa (P6.2)

Por padrão, o ADK grava nos spans o pedido e a resposta do modelo. Três variáveis de ambiente travam a captura
desligada, e a última impede que uma chamada a religue pelo `RunConfig`. Os testes provam os dois lados:

- **controle:** sem a trava, o CPF, a pergunta e a resposta aparecem nos spans;
- **com a trava:** nada disso aparece, nem quando a chamada pede o conteúdo.

Spans próprios, só com metadados: mascaramento por detector (quantidade e tipo de achado, por exemplo
`BRAZIL_CPF_NUMBER`), filtro de entrada (barrado, filtros, indisponível) e chamadas ao sistema de cartões.

**Conferido num trace real do CI:** 10 a 17 spans por turno, conforme o caminho no grafo; `llm_request` e
`llm_response` vazios (`{}`); nos rótulos, só modelo, tokens, motivo de parada e ids aleatórios. Aparece também
um span `BigQuery.insertRowsJson`, gerado pela própria biblioteca do BigQuery, com o caminho da tabela e sem as
linhas gravadas.

### Achados no caminho

**A API de telemetria recusava todos os spans, em silêncio.** O envio respondia 400 ("Resource is missing
required attribute gcp.project_id"). O servidor do ADK cria o provedor de traces sem esse atributo, e o erro só
aparecia no log do servidor, que o CI não guardava. Correção: o projeto entra nos atributos do recurso antes de o
servidor criar o provedor, e sem ele a exportação não é ligada.

**No CI, a credencial não gerava token.** A federação de identidade do GitHub exige escopo explícito; a
credencial de usuário, na máquina local, não exige. Por isso o envio funcionava localmente e falhava no CI.
Correção: escopo pedido ao obter a credencial. O CI passou a mostrar só as linhas do exportador no log do
servidor, sem o resto do log.

**O bucket de traces ficou em `us`.** O padrão de local dos buckets de observabilidade foi configurado para
southamerica-east1 antes do primeiro envio do P6.2, pela API REST, porque o comando não existe no gcloud GA. Mas
o bucket `_Trace` do projeto já existia desde 18/set, criado por traces anteriores, e o local de um bucket não
muda depois de criado. Decisão: aceitar `us` para traces, porque eles não levam dado pessoal (ver
[decisões](../decisoes.md)).

**Um trace antigo leva texto de conversa.** Esse bucket guarda um trace de 18/set, anterior à trava, com o
pedido e a resposta do modelo. São dados fictícios de desenvolvimento, e o trace expira com a retenção do bucket.
É exatamente o risco que a trava fecha.

## Custo e latência (P6.3)

O custo é calculado na consulta, não gravado na trilha: tokens do registro × preço da tabela
(`config/custo/precos.yaml`), com o preço vigente na data do turno. Os preços foram consultados em 7/out na
página oficial (região global, até 200 mil tokens de entrada). O Gemini 3.8 Flash custa USD 0,75 (entrada),
0,075 (cache) e 3,75 (saída) por milhão de tokens até 31/12/2026, e o dobro a partir de 2027.

Relatório dos dias 7 e 8/out, 162 turnos (avaliações no CI e testes locais):

| Etapa | Chamadas | p50 | p95 | Máx |
|---|---|---|---|---|
| turno inteiro | 162 | 6,3 s | 24,0 s | 39,9 s |
| classificador | 153 | 2,8 s | 17,3 s | 30,0 s |
| redator | 80 | 4,9 s | 22,9 s | 32,2 s |

| Etapa | Entrada | Saída | Pensamento | Custo médio por chamada |
|---|---|---|---|---|
| classificador | 435 | 28 | 133 | USD 0,00093 |
| redator | 652 | 94 | 428 | USD 0,00244 |

- **Cerca de USD 2 por mil turnos**, no preço promocional, só o LLM.
- **O pensamento é a maior parte do custo:** cerca de 54% no classificador e 66% no redator, que pensa 4,5
  tokens para cada token de resposta.
- **Dúvida sobre produtos é a intenção mais cara e mais lenta** (USD 3,14 por mil turnos, p50 de 9,7 s),
  porque passa pela busca e pelo redator. Bloqueio de cartão custa USD 0,77 por mil.
- **Turno resolvido por regra não custa nada:** barrado pelo filtro e aviso de número de cartão respondem em
  menos de 1,3 s, sem LLM.
- **O revisor (2.5 Pro) não foi chamado** nesses dois dias; o custo dele ainda não aparece.

### A latência varia com o momento, não com o código

No CI do `822ca34`, os mesmos 31 casos ficaram bem mais lentos: turno com p50 de 13,2 s e p95 de 48,5 s;
classificador e redator no p95 em 30 s e 40 s, as duas tentativas estouradas. Dois turnos foram interrompidos e
três casos ficaram sem nota. Latência do classificador por hora, pela trilha:

| Hora (UTC) | Execução | p50 | p95 | Sem resposta |
|---|---|---|---|---|
| 07/out 14h | CI do P6.1 | 3,6 s | 17,6 s | 0 |
| 07/out 18h | CI do P6.2 | 2,7 s | 4,7 s | 1 |
| 08/out 13h | CI do `2187ec4` | 3,0 s | 10,9 s | 1 |
| 08/out 14h | CI do `822ca34` | 7,3 s | 30,0 s | 2 |

Entre as duas últimas, o caminho do agente não mudou (o `822ca34` só acrescentou o relatório). É a variação do
serviço do Gemini. Consequência para a avaliação: um caso não executado conta como não aprovado, então o
resultado de uma rodada depende do momento em que ela roda. Nessa rodada, os quatro casos de manipulação
executados foram barrados corretamente.

**A latência é o principal risco operacional do protótipo, não o custo.** As alavancas são limitar o pensamento
e revisar os prazos das chamadas.

## Achados que distorciam os dados

**No streaming, uma chamada virava várias.** O ADK chama o gancho de fim de chamada a cada pedaço da resposta.
O plugin registrava cada pedaço: uma chamada do classificador virou três registros, dois com modelo vazio e sem
duração. Só a interface web e o teste de integração usam streaming; o CI não. Correção: só a resposta completa
fecha a chamada, com teste que reproduz o defeito. Os registros antigos continuam na trilha, e o relatório os
mostra como "modelo sem preço", fora do total.

**O teste de integração gravava na trilha real.** O teste que sobe o servidor completo usava o `.env` local e
gravava os turnos de teste no Cloud Storage e no BigQuery. Os que já foram para o bucket não podem ser apagados
(retenção travada). Correção: o teste desliga os destinos na nuvem (`AUDITORIA_NA_NUVEM=false`) e grava o diário
numa pasta temporária; o servidor avisa na partida quando a auditoria na nuvem está desligada. Conferido: zero
turnos no BigQuery depois do teste.

## Limites

- **Custo estimado, não fatura:** só o LLM. SDP e Model Armor, cobrados por volume analisado, ficam de fora.
- **Percentil por posição mais próxima:** o p95 é um tempo que aconteceu, não interpolado; com poucos turnos
  por intenção, oscila muito.
- **Traces em `us`**, sem dado pessoal, mas com ids de sessão que a trilha liga ao cliente; o acesso à trilha
  continua restrito.
- **Só o CI envia traces.** Na máquina local, só com `EXPORTAR_TRACES=true`.
- **A listagem da API de traces não mostra os spans enviados pela API de telemetria**; a busca pelo id funciona.
- **Teste instável:** o caminho síncrono do teste de integração leva de 41 a 57 s sem nenhum prazo estourado,
  perto do limite de 60 s do teste; uma chamada lenta ao Gemini o derruba.
- **Rodar o relatório carrega o agente inteiro** (o pacote `app` importa o agente), criando clientes que ele
  não usa.
