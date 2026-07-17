# Agente jurídico — intimações, andamentos e providências

Automatiza a rotina do jurídico interno. O Monday é o **caminho final**: os
prazos chegam por e-mail, o agente entra no processo para entender o que
aconteceu e só então cadastra a providência no quadro.

## Fluxo

```
1. E-MAIL (a origem dos prazos)
   • encaminhados do e-mail pessoal → caixa Gmail corporativa (Fwd:/Enc:)
   • Domicílio Judicial Eletrônico / andamentos do CNJ (remetentes .jus.br)
   • pushes processuais
                │
                ▼  parser: nº CNJ, tipo, prazo, audiência, vara
2. ENTRAR NO PROCESSO (caso a caso)
   • Comunica/PJe (Domicílio Judicial): teor integral das comunicações
   • DataJud (CNJ): últimos andamentos
                │
                ▼
3. ENTENDER O QUE ACONTECEU
   • análise do caso (Gemini, se GEMINI_API_KEY; senão resumo heurístico)
   • triagem: contestar, manifestar, audiência, recurso ou só ciência
                │
                ▼
4. MONDAY (caminho final)                 + eventos JSONL p/ agentes futuros
   item com providência, prazo fatal,      (elaborar_peca /
   audiência, teor e análise                atualizar_contingencia)
```

## Comandos

```bash
juridico list                      # intimações não lidas (JSON)
juridico process                   # fluxo completo: processo + análise + Monday + eventos
juridico process --dry-run         # só mostra a triagem, sem efeitos colaterais
juridico process --no-datajud      # não consulta andamento no DataJud
juridico process --no-comunica     # não busca teor no Domicílio Judicial
juridico comunicacoes --numero "1001234-56.2026.8.26.0100" # teor das comunicações
juridico andamentos --numero "1001234-56.2026.8.26.0100"   # andamento processual
juridico events --type elaborar_peca                        # fila p/ agentes futuros
```

A autenticação Google é compartilhada com o pipeline Procon: `procon-email auth`
(mesmo token em `credentials/gmail-token.json`).

## De onde vêm os e-mails

O agente reconhece intimações por três caminhos:

1. **Encaminhados do e-mail pessoal** para a caixa corporativa. Cadastre os
   remetentes autorizados em `JURIDICO_FORWARDER_EMAILS`
   (ex.: `JURIDICO_FORWARDER_EMAILS="seu.email@gmail.com"`); e-mails desses
   remetentes são aceitos sempre que o assunto/corpo tiver sinais judiciais
   (número CNJ + termos processuais), incluindo prefixos `Fwd:`/`Enc:`.
2. **Domicílio Judicial Eletrônico / tribunais** — qualquer remetente `.jus.br`.
3. **Qualquer outro remetente** cujo corpo contenha um encaminhamento de
   `.jus.br` ou número CNJ com termos processuais claros.

## O que o parser extrai

| Campo | Como |
|-------|------|
| Número do processo | Numeração única CNJ (`NNNNNNN-DD.AAAA.J.TR.OOOO`), com ou sem formatação — obrigatório |
| Tribunal | Inferido dos dígitos J.TR (TJSP, TRF3, TRT2, TST, STJ…) |
| Vara/comarca | Regex sobre "Vara", "Juizado", "Foro", "Comarca" |
| Tipo | Citação, intimação, audiência, sentença, decisão/despacho |
| Prazo | "prazo de 15 (quinze) dias úteis/corridos" ou data explícita |
| Audiência | Data e hora ("designada para o dia 05/08/2026 às 14:30") |

## Triagem de providências

| Situação | Ação | Prazo padrão (se não houver no e-mail) |
|----------|------|----------------------------------------|
| Citação | Apresentar contestação | 15 dias úteis (CPC art. 335) |
| Sentença | Analisar e avaliar recurso | 15 dias úteis |
| Audiência designada | Preparar e comparecer | data da audiência |
| Pedido de manifestação | Apresentar manifestação | 5 dias úteis (CPC art. 218 §3º) |
| Arquivamento/trânsito em julgado | Tomar ciência | — (não cria item no Monday) |

Prazos em dias úteis excluem o dia do começo e prorrogam o termo final para o
próximo dia útil (fins de semana; feriados forenses exigem calendário do
tribunal e ficam fora do MVP — confira o termo final no sistema do tribunal).

## Entrar no processo: teor + andamentos

Antes de cadastrar no Monday, o agente "entra no processo" por duas fontes
públicas do CNJ:

- **Comunica/PJe (Domicílio Judicial Eletrônico)** — teor integral das
  comunicações expedidas para o processo, sem chave de API. Quando o e-mail
  encaminhado vem sem detalhes ("segue intimação"), é o teor oficial que define
  tipo, prazo e vara na triagem.
- **DataJud** — últimos andamentos ([API pública](https://datajud-wiki.cnj.jus.br/api-publica/)).
  Configure a chave (pública, publicada pelo CNJ) em `DATAJUD_API_KEY`. O alias
  do tribunal é inferido do número CNJ (ex.: `tjsp`, `trf3`, `trt2`); use
  `--alias` para forçar.

Falha em qualquer uma das consultas não bloqueia o fluxo (o erro fica anotado
no resultado).

## Análise caso a caso

Com `GEMINI_API_KEY` configurada (a mesma do pipeline Procon), o agente gera um
parecer curto — "o que aconteceu / providência / pontos de atenção" — a partir
do e-mail, do teor das comunicações e dos andamentos. Sem a chave (ou se o
Gemini falhar), cai para um resumo heurístico estruturado. A análise vai para a
coluna `Análise` do Monday e para os eventos de handoff.

## Monday

O item é criado no board definido por `MONDAY_JURIDICO_BOARD_NAME` (padrão
`processos`; ou `MONDAY_JURIDICO_BOARD_ID`), grupo `MONDAY_JURIDICO_GROUP_NAME`
(padrão `providencias pendentes`). Colunas são mapeadas por título:

| Coluna (título contém) | Conteúdo | Tipo sugerido |
|------------------------|----------|---------------|
| Nº do Processo / CNJ | número CNJ | text |
| Tribunal | sigla (TJSP…) | text |
| Vara / Juizado / Comarca | órgão | text |
| Tipo de Intimação | Citação, Sentença… | status |
| Providência | ação da triagem | text |
| Prazo Fatal | data-limite | date |
| Audiência | data + hora | date |
| Teor / Resumo | resumo da intimação | long_text |
| Análise / O que aconteceu | parecer do caso (Gemini ou heurístico) | long_text |
| ID Intimação | id do e-mail (deduplicação) | text |

Itens só são criados quando a triagem exige providência; "tomar ciência" não
gera item. A deduplicação usa a coluna `ID Intimação` (se existir) e o estado
local `data/juridico-processed.json`.

## Handoff para os agentes futuros

Cada intimação processada emite eventos append-only em
`data/juridico-events.jsonl`, contrato de integração dos dois agentes ainda
não implementados:

- `elaborar_peca` — para o agente que vai **elaborar e protocolizar peças
  processuais** (emitido quando a providência exige peça: contestação,
  manifestação, recurso). Payload: tipo, tribunal, vara, resumo, prazo fatal e
  link do item no Monday.
- `atualizar_contingencia` — para o agente que vai **atualizar relatórios
  contingenciais** (emitido para toda intimação). Payload: resumo, andamentos
  do DataJud e a flag `affects_contingency` (depósitos, penhoras, alvarás,
  condenações, execução).

## Variáveis de ambiente

| Variável | Obrigatória para | Descrição |
|----------|------------------|-----------|
| `JURIDICO_FORWARDER_EMAILS` | e-mails encaminhados do pessoal | Remetentes autorizados, separados por vírgula |
| `DATAJUD_API_KEY` | consulta de andamentos | Chave pública da API DataJud/CNJ |
| `GEMINI_API_KEY` | análise com IA (opcional) | Mesma chave do pipeline Procon |
| `MONDAY_API_TOKEN` | cadastro no Monday | Mesmo token do pipeline Procon |
| `MONDAY_JURIDICO_BOARD_NAME` | — (padrão `processos`) | Board de processos judiciais |
| `MONDAY_JURIDICO_BOARD_ID` | — | Id do board (vence o nome) |
| `MONDAY_JURIDICO_GROUP_NAME` | — (padrão `providencias pendentes`) | Grupo do board |
| `JURIDICO_GMAIL_QUERY` | — | Sobrescreve o filtro Gmail padrão |

## Limitações do MVP

- Prazos não consideram feriados forenses nem suspensões de prazo.
- A triagem é heurística (palavras-chave); revise a providência sugerida.
- Tribunais eleitorais/militares têm suporte parcial no alias do DataJud.
- Os agentes de peças e de contingência ainda não existem: os eventos ficam
  na fila JSONL aguardando os consumidores.
