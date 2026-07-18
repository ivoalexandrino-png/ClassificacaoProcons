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
juridico boards --filter prazos    # inspeciona quadros do Monday e o mapeamento
juridico events --type elaborar_peca                        # fila p/ agentes futuros
```

A autenticação Google é compartilhada com o pipeline Procon: `procon-email auth`
(mesmo token em `credentials/gmail-token.json`).

## De onde vêm os e-mails

O agente reconhece intimações por três caminhos:

1. **Encaminhados do e-mail pessoal** para a caixa corporativa (a mesma do
   Procon). Remetentes autorizados por padrão: `ivo.alexandrino@hotmail.com`,
   `adv.ialexandrino@gmail.com` e `adv.ivoalexandrino@gmail.com`
   (sobrescreva com `JURIDICO_FORWARDER_EMAILS`, separados por vírgula).
   E-mails desses remetentes são aceitos sempre que o assunto/corpo tiver
   sinais judiciais (número CNJ + termos processuais), incluindo `Fwd:`/`Enc:`.
2. **Domicílio Judicial Eletrônico / tribunais** — qualquer remetente
   `.jus.br`, incluindo o oficial `domicilio.comunicacoes@cnj.jus.br`.
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

### Triagem ciente do estágio do processo

Pushes chegam atrasados ou repetidos: um aviso de citação pode se referir a um
processo que já teve contestação, acordo e sentença. Antes de fechar a
providência, o agente cruza a triagem do e-mail com os andamentos do DataJud e
detecta o **marco de estágio mais avançado** (contestação → sentença → acordo →
encerramento). Se a providência do e-mail já foi superada, ela é **substituída
pela providência específica do estágio atual**, com prazo — o andamento
específico vai para o Monday em vez de virar "tomar ciência":

| Marco no DataJud | Providência cadastrada | Prazo (dias úteis do push) |
|------------------|------------------------|----------------------------|
| Trânsito em julgado / arquivamento / baixa / extinção | Verificar encerramento e obrigações finais | 5 |
| Acordo homologado (Homologação de Transação) | Acompanhar cumprimento do acordo homologado | 10 |
| Sentença (procedência/improcedência) | Analisar sentença e avaliar recurso | 15 (prazo legal estimado) |
| Contestação já apresentada | Acompanhar andamento do processo | 10 |

O motivo e o andamento específico ficam em `stage_note` (entra na análise e,
nos quadros sem coluna de análise, vira update no item). Os prazos de
acompanhamento contam do recebimento do push — o de recurso é estimativa do
prazo legal; confirme a data de intimação no tribunal.

**Margem de segurança:** a data lançada nas colunas de prazo do Monday é
sempre **2 dias úteis antes do prazo fatal real** (`MONDAY_SAFETY_BUSINESS_DAYS`
em `juridico/monday.py`). O prazo fatal real fica registrado na análise e na
anotação do item ("Prazo fatal real: … Lançado no quadro em …"). Datas de
audiência não são antecipadas — audiência é evento, não prazo.

Pushes de **mera ciência** também são cruzados: se o processo tem sentença,
acordo ou encerramento nos últimos 30 dias, o agente cadastra a providência
específica em vez de deixar passar (marcos mais antigos não reabrem casos).

O `--dry-run` também consulta o DataJud/Comunica (somente leitura), então a
triagem exibida já é a ciente do estágio. Sem `DATAJUD_API_KEY` (ou com
`--no-datajud`), a reclassificação não acontece — revise a providência sugerida.

## Entrar no processo: teor + andamentos

Antes de cadastrar no Monday, o agente "entra no processo" por duas fontes
públicas do CNJ:

- **Comunica/PJe (Domicílio Judicial Eletrônico)** — teor integral das
  comunicações expedidas para o processo, sem chave de API. Quando o e-mail
  encaminhado vem sem detalhes ("segue intimação"), é o teor oficial que define
  tipo, prazo e vara na triagem. **Atenção:** o CloudFront do CNJ bloqueia
  requisições de fora do Brasil (HTTP 403) — de VMs no exterior (Cloud Agents,
  runners do GitHub) o teor não é anexado; o fluxo segue com o e-mail + DataJud
  e o erro fica anotado no resultado. Para ter o teor, rode de IP brasileiro
  (ex.: Cloud Run em `southamerica-east1`).
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

## Monday (caminho final)

Dois quadros recebem itens automaticamente:

- **`prazos`** — toda providência com prazo (contestar, manifestar, recurso…).
  Board configurável via `MONDAY_JURIDICO_BOARD_NAME`/`_ID` (padrão `prazos`).
- **`audiências`** — quando a intimação marca audiência, o agente também cria
  item no board de audiências (`MONDAY_AUDIENCIAS_BOARD_NAME`/`_ID`, padrão
  `audiencias`), **sem excluir o prazo**: um mesmo processo pode ter prazo de
  contestação no `prazos` e audiência no `audiências`.

O grupo é configurável (`MONDAY_JURIDICO_GROUP_NAME` / `MONDAY_AUDIENCIAS_GROUP_NAME`).
No board `prazos`, o padrão é o grupo **"Prazos Processos"**; se o grupo
configurado não existir, o item entra no primeiro grupo do board. O board é
localizado por nome normalizado (aceita "Prazos", "prazos" etc.). Use
`juridico boards --filter prazos` para inspecionar os quadros visíveis, seus
grupos, colunas e o mapeamento que o agente detecta em cada coluna.

### Engrenagem entre quadros (casos, KPIs)

O quadro **Processos Judiciais** é o registro-mestre dos casos — citações
inauguram casos lá, e automações do Monday alimentam o quadro de audiências a
partir dele. A cada intimação processada, o agente gira as engrenagens
(`juridico/casos.py`):

1. **Localiza o caso** pelo número CNJ na coluna "Número" (Processos
   Judiciais) ou "Nº.: de Processo" (Processos Trabalhista — segmento J=5 da
   numeração CNJ decide o quadro).
2. **Conecta os itens criados** em `prazos`/`audiências` ao caso pelas colunas
   de conexão de quadros ("Processos Consumidores"/"Processos Judiciais").
3. **Anota a movimentação** na timeline do caso (providência + análise).
4. **Marcos inequívocos atualizam o caso**: acordo homologado → Decisão
   Judicial "Acordo"; trânsito em julgado/arquivamento → Status "Encerrado".
   Sentenças não definem sozinhas o resultado (procedente para quem?) e ficam
   para revisão humana; o rótulo só é escrito se existir na coluna.
5. **KPI - Processos Consumidores**: a linha do processo (localizada pelo CNJ)
   recebe Resultado "Acordo" + Data da Decisão, ou Situação "Arquivado" no
   encerramento. Linha inexistente **não** é criada e valores financeiros
   (condenação, pago, provisão, saving) seguem manuais — não vêm no DataJud.
6. **Citação de processo sem caso** cria o item no grupo "Processos
   Consumidores Ativos" com o CNJ preenchido (trabalhistas não são criados
   automaticamente — estrutura mais manual).

O resultado de cada intimação traz `case_sync_note` com as ações executadas.
Boards podem ser fixados por id com `MONDAY_PROCESSOS_BOARD_ID`,
`MONDAY_TRABALHISTA_BOARD_ID` e `MONDAY_KPI_BOARD_ID` (senão, localizados por
nome). Roadmap: preencher valores de condenação/pagamento a partir do teor
das decisões (exige Comunica/PJe, bloqueado fora do Brasil) e criar linhas de
KPI para anos novos.

Colunas são mapeadas por título:

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

Itens de prazo só são criados quando a triagem exige providência; "tomar
ciência" não gera item (audiência marcada gera item no board de audiências
mesmo assim).

A deduplicação tem três camadas:

1. estado local `data/juridico-processed.json` (mesmo e-mail nunca reprocessa);
2. coluna `ID Intimação`, quando o board tiver uma (mesmo e-mail reprocessado);
3. **conteúdo, por processo** (board `prazos`): antes de criar, o agente busca
   itens do mesmo processo. Se já existe item com a **mesma providência**, ou
   com providência de **fase posterior** (ex.: "Analisar sentença" já no board
   e chega um push atrasado de citação pedindo "Apresentar contestação"), o
   item novo **não é criado** — o existente recebe uma anotação (update) com o
   e-mail novo e o prazo sugerido. Providência de fase mais avançada que a do
   item existente cria item novo normalmente. No board `audiências` a
   deduplicação continua pelo nome do item (`processo — Audiência data`).

A ordem de fases usada na camada 3 é: contestação → manifestação/audiência/
acompanhamento → recurso → acordo → encerramento. Itens com nome fora do
padrão `processo — providência` são ignorados pela deduplicação (nunca
bloqueiam a criação).

**Prazos já cumpridos não contam:** itens em grupos de concluídos (título com
"cumprido", "concluído", "finalizado", "resolvido", "feito" ou "done") não
cobrem intimações novas — um prazo cumprido no passado não pode fazer o agente
descartar um prazo novo do mesmo processo como duplicado.

Proteções do mapeamento (calibradas com os quadros reais):

- A data da audiência só é escrita em colunas do tipo **data** — "Link
  Audiência" e "Orientações de Audiência" ficam para preenchimento manual.
  No quadro de audiências, a coluna chamada só "Data" recebe a data/hora da
  audiência; o horário é convertido de Brasília para UTC (o Monday exibe no
  fuso da conta).
- Colunas com "Responsável" no título nunca são preenchidas automaticamente.
- "Processo Administrativo", "Processos Consumidores" e afins não recebem o
  número CNJ (pertencem ao domínio Procon/consumidores).
- O número CNJ só é escrito em colunas de **texto** ("Número do Processo") —
  "Processos Judiciais" (conexão entre quadros) exige id de item e fica para
  vínculo manual.
- Itens de audiência duplicados (mesmo processo + mesma data/hora) não são
  recriados: o item existente recebe anotação, como no quadro de prazos. Sem
  coluna de análise no quadro, o parecer vai como update no item.

## E-mails sem número CNJ (`needs_review`)

Alguns avisos (ex.: "ENC: [PROJUDI] Informação de intimação/citação") não
trazem o número do processo no corpo. Eles saem com status `needs_review` no
resultado do `process`: continuam **não lidos** na caixa, não entram no estado
local (reaparecem a cada execução) e não derrubam a execução. Trate-os
manualmente ou responda com o número CNJ para reprocessar.

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

## Execução horária (GitHub Actions)

O workflow `juridico-hourly.yml` roda `juridico process --max-results 20
--no-comunica` a cada hora (minuto 30, deslocado do `procon-hourly`), com os
secrets `GMAIL_OAUTH_JSON`/`GMAIL_TOKEN_JSON`, `MONDAY_API_TOKEN`,
`GEMINI_API_KEY` e `DATAJUD_API_KEY`. O estado `data/` (intimações já
processadas + eventos de handoff) persiste entre execuções via cache do
Actions com chave rolante (`juridico-pipeline-state-<run_id>`, restaurada por
prefixo). O `workflow_dispatch` aceita `dry_run` para inspecionar a triagem
sem efeitos colaterais. `--no-comunica` porque os runners ficam fora do Brasil
e o CloudFront do CNJ responde 403.

## Variáveis de ambiente

| Variável | Obrigatória para | Descrição |
|----------|------------------|-----------|
| `JURIDICO_FORWARDER_EMAILS` | — (padrão: e-mails do Ivo) | Remetentes autorizados, separados por vírgula |
| `DATAJUD_API_KEY` | consulta de andamentos | Chave pública da API DataJud/CNJ |
| `GEMINI_API_KEY` | análise com IA (opcional) | Mesma chave do pipeline Procon |
| `MONDAY_API_TOKEN` | cadastro no Monday | Mesmo token do pipeline Procon |
| `MONDAY_JURIDICO_BOARD_NAME` | — (padrão `prazos`) | Board de prazos |
| `MONDAY_JURIDICO_BOARD_ID` | — | Id do board de prazos (vence o nome) |
| `MONDAY_JURIDICO_GROUP_NAME` | — (padrão: primeiro grupo) | Grupo do board de prazos |
| `MONDAY_AUDIENCIAS_BOARD_NAME` | — (padrão `audiencias`) | Board de audiências |
| `MONDAY_AUDIENCIAS_BOARD_ID` | — | Id do board de audiências (vence o nome) |
| `MONDAY_AUDIENCIAS_GROUP_NAME` | — (padrão: primeiro grupo) | Grupo do board de audiências |
| `MONDAY_PROCESSOS_BOARD_ID` | — (padrão: por nome) | Id do quadro-mestre Processos Judiciais |
| `MONDAY_TRABALHISTA_BOARD_ID` | — (padrão: por nome) | Id do quadro Processos Trabalhista |
| `MONDAY_KPI_BOARD_ID` | — (padrão: por nome) | Id do quadro KPI - Processos Consumidores |
| `JURIDICO_GMAIL_QUERY` | — | Sobrescreve o filtro Gmail padrão |

## Limitações do MVP

- Prazos não consideram feriados forenses nem suspensões de prazo.
- A triagem é heurística (palavras-chave); revise a providência sugerida.
- Tribunais eleitorais/militares têm suporte parcial no alias do DataJud.
- Os agentes de peças e de contingência ainda não existem: os eventos ficam
  na fila JSONL aguardando os consumidores.
