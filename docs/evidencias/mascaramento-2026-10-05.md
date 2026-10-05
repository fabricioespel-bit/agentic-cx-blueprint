# Evidência: mascaramento de dados pessoais (5/out/2026)

O texto da conversa vai ao Gemini no endpoint global; a arquitetura exige que chegue pseudonimizado. O P4.1
põe o mascaramento antes da sessão e do LLM: o Sensitive Data Protection (SDP) do Google, chamado no endpoint
regional `southamerica-east1`, e regras locais com dígito verificador, juntos. Dados fictícios.

## Sondagem do SDP com textos em português

Antes de escrever o mascarador, 11 frases foram enviadas ao SDP regional (`dlp.southamerica-east1.rep.googleapis.com`),
para decidir o desenho com dados.

| Frase | Detectado | Confiança |
|---|---|---|
| CPF com pontuação | `529.982.247-25` | muito provável |
| CPF sem pontuação | `52998224725` | provável |
| Cartão com espaços | `4111 1111 1111 1111` | muito provável |
| Cartão sem espaços | `4111111111111111` | possível |
| Nome completo | `Maria Aparecida dos Santos` | possível |
| Endereço | `Rua das Flores, 123, São Paulo` | provável |
| E-mail e celular | os dois | muito provável |
| "Sou o João" | nada | — |

Nenhum falso positivo em "final 1234", "final 5678", "R$ 19,90", data, "3000 reais" e "Cartão Exemplo
Platinum". Latência mediana de 77 ms por mensagem (a primeira chamada, com a conexão, levou 3,3 s).

**Decisões que saíram daqui:** limite "possível" (cartão sem espaços e nome só aparecem nesse nível); regras
locais com Luhn e cálculo do CPF rodando sempre, como segunda camada para os dados mais graves; primeiro nome
isolado aceito como limitação.

## O detalhe do ADK que um teste provou

O mascaramento é um plugin do ADK (`on_user_message_callback`), que roda antes de a mensagem ser gravada na
sessão. O gancho permite devolver uma mensagem nova, mas o runner guarda a mensagem original como entrada do
grafo antes de chamá-lo. Com uma mensagem nova, a sessão fica mascarada e o classificador recebe o texto
original. O plugin altera a própria mensagem; o teste `test_classificador_e_sessao_recebem_o_texto_mascarado`
falha na outra versão (o classificador recebe `529.982.247-25`) e passa nesta.

Dois defeitos de montagem, ambos silenciosos, mostram por que os testes existem: um gancho com o nome
`on_user_message` (o ADK nunca o chamaria e nada avisaria; hoje um teste garante que o método sobrescreve o
gancho) e um `Achado` sem o tipo no detector do SDP (cada chamada falharia e as regras locais assumiriam
sozinhas, deixando nomes em claro; o teste com o SDP falso pega).

## Medido no CI

Quatro casos novos no conjunto de avaliação (grupo `privacidade`) e a métrica `sem_dado_pessoal`, que procura
os dados de cada caso no trace do agente (estado gravado, saídas dos nós) e na resposta. Execução no GitHub
Actions, com credencial temporária por federação de identidade (37357854220):

| Caso | Comportamento | Chamadas ao LLM | Dado pessoal |
|---|---|---|---|
| CPF no pedido de bloqueio | pergunta qual cartão | 1 | nenhum vazou |
| Número completo de cartão | aviso fixo | **0** | nenhum vazou |
| Nome completo numa dúvida | responde com valor e fonte | 2 | nenhum vazou |
| E-mail numa dúvida | responde com valor e fonte | 2 | nenhum vazou |

O caso do nome só passa com o SDP: as regras locais não detectam nomes. Nenhum aviso de falha do SDP no log.
Os demais grupos ficaram como antes (as três lacunas da busca lexical seguem falhando de propósito).

## Achados da execução

- **Limpeza do CI travava 5 minutos.** O agente subia com `uv run` em segundo plano e não era encerrado; o
  processo segurava a trava do cache do uv, e a limpeza do `setup-uv` desistia após 300 s, marcando a
  execução como falha com todos os passos da avaliação verdes. Correção: subir pelo executável do ambiente e
  encerrar o agente no fim.
- **O juiz oscilou.** Nesta execução, ele marcou como `excesso` os "débitos automáticos" de
  `compras_apos_bloqueio`, o mesmo detalhe que julgara "da mesma situação" na calibração e na rodada 3. O CI
  guardava só os resultados, sem o texto da resposta, então não foi possível separar oscilação do juiz de
  mudança na redação. Agora os traces também são guardados. Antes de um gate, `excesso` deve ser não
  bloqueante, ou o juiz precisa de várias amostras com votação.

## Limites

- Primeiro nome isolado não é detectado.
- O limite "possível" foi escolhido com 11 frases; falsos positivos seguem monitorados pela avaliação.
- Custo do SDP: cobrança por volume inspecionado; o valor por mensagem ainda não foi conferido na página de
  preços.
- No protótipo, o plugin faz o papel do gateway; em produção, o mascaramento fica no gateway de canal.
