# Evidência: escalonamento ao atendimento humano (6/out/2026)

O agente encaminha a conversa a um atendente em três situações: o cliente pede, o cliente aceita a oferta
("sim" depois de uma resposta que oferece atendimento) ou três falhas seguidas na sessão. O atendente recebe um
resumo montado por código a partir do histórico que a auditoria mantém no estado, já mascarado; sem LLM, o
resumo só contém o que o agente registrou. No protótipo, o chamado vai para uma fila local
(`artifacts/atendimento/fila.jsonl`) com protocolo `ATD-`. Dados fictícios.

## Com o modelo real

Dois casos novos no conjunto de avaliação (grupo `escalonamento`), com o classificador real (`gemini-3.8-flash`),
local e no CI:

| Caso | Resultado |
|---|---|
| "Quero falar com um atendente" | encaminhado (`pede_atendente` marcado) |
| "Não consigo bloquear meu cartão pelo app, me passa para uma pessoa" | encaminhado: intenção de bloqueio e pedido de atendente na mesma mensagem, o pedido prevalece |

Chamado gravado na fila pela avaliação local:

```
ATD-E7C2ED60 pedido_do_cliente
   Atendimento ATD-E7C2ED60: cliente cli-1, canal whatsapp, nível 1.
   Motivo do encaminhamento: pedido do cliente.
   Última mensagem (mascarada): "Não consigo bloquear meu cartão pelo app, me passa para uma pessoa"
```

Cada caso da avaliação é uma sessão de um turno, então o histórico vem vazio. Conversas de vários turnos estão
nos testes de fluxo: o resumo lista os turnos na ordem ("1. bloquear_cartao_temporario: confirmacao_pedida",
"2. bloquear_cartao_temporario: cancelado"), o aceite da oferta registra o motivo da negação anterior e a
terceira falha seguida encaminha sem pedido.

## Achado: o redator copiou o id da fonte com colchetes

Na mesma avaliação local, `juros_rotativo`, que passara em todas as rodadas, recusou:

```
redator:     "fontes": ["[fatura-e-pagamento#pagamento-minimo-e-credito-rotativo]"]
verificação: "fonte fora da busca: [fatura-e-pagamento#pagamento-minimo-e-credito-rotativo]"
revisor:     repetiu os colchetes → reprovado de novo → recusa ao cliente
```

O pedido mostra cada trecho como `[id] título`, e a instrução dizia para copiar os ids "como aparecem entre
colchetes"; o Flash leu como "com os colchetes". A verificação recusou corretamente (falha segura), mas o cliente
ficou sem uma resposta que o corpus tinha. Foi também o primeiro acionamento do revisor (Pro) numa avaliação: a
mensagem de problema não dizia por que a fonte era inválida, e ele repetiu o erro.

**Correção:** instrução "só o id, sem os colchetes (ex.: `cartao-classico#anuidade`)" e normalização em código
(colchetes e espaços nas pontas saem antes da verificação; o id ainda precisa ser um trecho recuperado). A saída
real do redator, reprocessada pela verificação corrigida sem nova chamada ao LLM, passou a ser aprovada:
*"…os juros do crédito rotativo são de 9,90% ao mês sobre o saldo restante. O rotativo vale só até a fatura
seguinte…"*.

## Limites

- A fila é um arquivo local; a integração com a plataforma de atendimento humano está proposta.
- Tema sensível e frustração do cliente, gatilhos previstos na arquitetura, exigem interpretação (classificador
  próprio, avaliado); estão propostos.
- O histórico guarda os 10 últimos turnos da sessão.
