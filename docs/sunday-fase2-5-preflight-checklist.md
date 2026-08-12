# Fase 2.5 — Configuração manual assistida e preflight final (Onda 1)

> **Status:** leitura e checklist apenas. Nenhum POST/PATCH/DELETE foi feito em nenhum
> board real (Sunday ou Monday) nesta etapa. Nenhum item foi migrado.

## 0. Achado crítico — não existe Fase 2 (F2.x) registrada no repositório

Antes de qualquer coisa: **este documento não conseguiu "usar exclusivamente
`docs/migracao-monday-sunday-legal.md`, especialmente F2.3/F2.12/F2.14"** porque essas
seções **não existem**. `docs/migracao-monday-sunday-legal.md` hoje só tem a **Fase 0**
(até F0.14 — microtestes A/B/C de `board_relation`, status customizado e Área). Não há
nenhuma Fase 1 ou Fase 2 documentada, nem PR/branch mesclado que as contenha (verificado
em todo o histórico de commits e PRs do repositório).

Também não existe no repositório:

- uma lista das "28 identidades técnicas Monday" para matching de usuários;
- a lista dos "30 desativados" (a decisão "migrar sem responsável" foi aceita como
  definitiva **porque você a declarou nesta mensagem**, não porque está registrada aqui);
- um de-para de status validado para os boards Prazos/Audiências/Processos
  Judiciais/Processos Trabalhista/KPI/Procons;
- uma especificação de colunas para o board Contratos (87) equivalente à que existe para
  Controle Assinaturas.

O que **existe** e foi usado como base real (em vez de inventar):

1. **Leitura ao vivo do Sunday** (somente `GET`, token/URL dos secrets do ambiente) —
   `docs/sunday-fase2-5-readonly-report.json`, gerado por
   `scripts/sunday_fase2_5_readonly_validation.py`.
2. **Leitura ao vivo do Monday** (somente `query` GraphQL) dos 8 boards de origem reais —
   `docs/sunday-fase2-5-monday-snapshot.json`, gerado por
   `scripts/monday_readonly_legal_boards_snapshot.py`.
3. `docs/controle-sunday-greenfield.md` — único documento com decisão arquitetural
   **aprovada** (ainda que rotulada `SUNDAY_SCHEMA_READY_FOR_APPROVAL`, não "F2.x") para o
   board 77 (Controle de Assinaturas).
4. Leitura estática do código atual (`juridico/monday.py`, `juridico/casos.py`,
   `juridico/acessos.py`, `monday/mapping.py`, `monday/client.py`,
   `contratos/constants.py`, `contratos/monday_contracts.py`, `contratos/parent_resolver.py`)
   para saber exatamente quais títulos de coluna, labels e `board_relation` o pipeline
   atual espera encontrar por título.

Este checklist é construído sobre esses 4 pilares. Onde uma decisão de negócio genuína
faltava (ex.: qual conjunto de labels usar, se difere do Monday atual), isso está marcado
explicitamente como **pendente de decisão humana**, e não foi inventado.

---

## 1. Validação inicial de credenciais

| Secret | Disponível neste ambiente |
|---|---|
| `SUNDAY_API_TOKEN` | **Sim** |
| `SUNDAY_API_URL` | **Sim** |
| `MONDAY_API_TOKEN` | Sim (usado só para leitura, para reconstruir o schema real de origem) |

Nenhum valor de token foi exposto nesta conversa ou nos artefatos commitados.

## 2. Validação por leitura dos 8 boards (Sunday, workspace 22)

Fonte: `GET /workspaces/22`, `GET /boards`, `GET /boards/{id}`,
`GET /boards/{id}/columns`, `GET /boards/{id}/groups`, `GET /boards/{id}/items`,
`GET /boards/{id}/automations` — todas com HTTP 200, nenhuma escrita.

| Sunday ID | Nome esperado | Nome real no Sunday | Workspace | Itens hoje | Grupos hoje | Colunas hoje |
|---|---|---|---|---|---|---|
| 72 | Legal - Audiências | **Legal - Audiências** ✅ | 22 ✅ | **9** (não está vazio) | `Itens`, `Audiencias Pendentes` | 5 (sistema) |
| 77 | Legal - Controle de Assinaturas | **Legal - Controle de Assinaturas - Jan & Luciano** ⚠️ | 22 ✅ | 0 | `Itens` | 5 (sistema) |
| 82 | Legal - Procons | **Legal - Procons** ✅ | 22 ✅ | 0 | `Itens` | 5 (sistema) |
| 83 | Legal - Prazos | **Legal - Prazos** ✅ | 22 ✅ | 0 | `Itens` | 5 (sistema) |
| 84 | Legal - Processos Judiciais | **Legal - Processos Judiciais** ✅ | 22 ✅ | 0 | `Itens` | 5 (sistema) |
| 85 | Legal - Processos Trabalhista | **Legal - Processos Trabalhista** ✅ | 22 ✅ | 0 | `Itens` | 5 (sistema) |
| 86 | Legal - KPI Processos Consumidores | **Legal - KPI Processos Consumidores** ✅ | 22 ✅ | 0 | `Itens` | 5 (sistema) |
| 87 | Legal - Contratos | **Legal - Contratos** ✅ | 22 ✅ | 0 | `Itens` | 5 (sistema) |

### ⚠️ Único mismatch — Board 77

Nome real: **"Legal - Controle de Assinaturas - Jan & Luciano"** (sufixo extra em
relação ao nome canônico pedido, "Legal - Controle de Assinaturas"). O **ID confere**
(77), o **workspace confere** (22), e este é claramente o **mesmo board** já registrado
desde a Fase 0 (lá aparecia como Sunday ID interno `"66"` → `board_id "77"` →
`"Legal - Controle de Assinaturas - Jan & Luciano"`; ver
`docs/migracao-monday-sunday-legal.md`). Por instrução explícita ("não renomeie nada"),
**não foi feita nenhuma alteração**. Este checklist usa o nome real do board em todas as
instruções de UI (procure por "Legal - Controle de Assinaturas - Jan & Luciano" na lista
de quadros do workspace 22), mas trata isso como o board 77 pedido.

**Nenhum outro ID/nome divergiu.** Não há necessidade de parar por qualquer um dos outros
7 boards.

### Colunas de sistema (idênticas nos 8 boards, já existentes — não recriar)

| Coluna | Tipo | `is_system` | Observação |
|---|---|---|---|
| `Nome` (`name`) | text | sim | Nome do item |
| `Status` (`status`) | status | sim | Usa `status_set` do board (3 opções genéricas: `A fazer`/`Follow-up`/`Feito`) — **não é o status de negócio**, ver §5 |
| `Responsável` (`owner`) | people | sim | — |
| `Data` (`target_date`) | date | sim | — |
| `Área` (`area`) | dropdown | sim | Estrutural; **ignorar** (ver §7) |

### `status_set` do board

Todos os 8 boards têm o **mesmo** `status_set` genérico de sistema:
`A fazer (to_do)` / `Follow-up (follow_up)` / `Feito (done, terminal)`. Isso confirma a
decisão do F0.14: **não usar o status de sistema do board como substituto do status de
negócio**. Cada status de negócio (Status do Prazo, Resultado do KPI, Situação, Status
Jan/Luciano/Geral, etc.) precisa ser uma **coluna de status customizada** própria.

### Automações

Nenhum board tem automação configurada hoje (`GET /boards/{id}/automations` retornou
lista vazia para os 8).

## 3. Matching de usuários

- `GET /users` (diretório do Sunday) retornou **`403 Forbidden`**: *"Acesso restrito à
  equipe de People e à liderança (CEO, VP, Diretoria)."* O token atual tem
  `access_level: contributor` / papel `member` no workspace 22 — sem privilégio para
  listar o diretório.
- **Resultado:** `MATCH EXATO: indisponível` / `SEM MATCH: indisponível` — não é possível
  calcular porque (a) o endpoint de usuários está bloqueado para este token e (b) não
  existe no repositório uma lista das "28 identidades técnicas Monday" para comparar.
  Nenhum número foi inventado.
- **30 desativados:** decisão definitiva aceita como você declarou —
  **migrar sem responsável, sem atribuir pessoa semelhante** (nenhum fuzzy match será
  feito quando a Fase 3 chegar).

Para desbloquear o matching real, é preciso um dos dois: (1) um token Sunday com papel
People/liderança, ou (2) a lista das 28 identidades técnicas Monday para eu, ao menos,
te dizer manualmente quantas aparecem/não aparecem por nome no board (sem acesso ao
diretório de e-mails).

---

## 4. Checklist manual — por board

Convenções usadas em todos os checklists abaixo:

- `[ ]` = ação a executar manualmente no app do Sunday.
- **Obrigatória: SIM** = bloqueia o dry-run/migração de dados da Onda 1 se ausente.
- **Obrigatória: NÃO** = útil/recomendado, mas a migração funciona sem.
- Toda tabela de "Status/labels" abaixo é a **extração ao vivo do Monday** (fonte real,
  não invenção) — é uma **proposta de carry-over 1:1**, não um de-para "Fase 2" (que não
  existe). Se você quiser labels diferentes das do Monday atual, me diga antes de criar.

### 4.1 BOARD: Legal - Contratos
### ID: 87

Board no Sunday: 5 colunas de sistema, 1 grupo (`Itens`), 0 itens, `capabilities.subitems
= false` (ver §6). Origem real no Monday: board `Contratos` (id `5385471914`), 1.119
itens, 17 grupos, 10 colunas.

**A) Colunas de sistema já existentes — não recriar**
- `Nome`, `Status` (genérico), `Responsável`, `Data`, `Área` — ver tabela do §2.

**B) Colunas customizadas a criar** (resolução por título no código atual —
`contratos/monday_contracts.py:1535-1576`, `contratos/parent_resolver.py:27`):

- [ ] Ação: criar coluna
  Nome exato: `Empresa`
  Tipo: Status (usar coluna de status customizada, não o Status de sistema)
  Opções: ver tabela abaixo
  Configuração: —
  Obrigatória: SIM
  Motivo: código busca coluna por título contendo "empresa"; carrega qual entidade
  contratante (B4A/MMKT/Itaro/Aurora/RV BVI/Jan) figurando no contrato

  | Label (Monday atual) |
  |---|
  | B4A |
  | MMKT |
  | Itaro |
  | Aurora |
  | RV BVI |
  | Jan |
  | B4A & MMKT |

- [ ] Ação: criar coluna
  Nome exato: `CNPJ outra Parte`
  Tipo: Texto
  Opções: —
  Configuração: —
  Obrigatória: SIM
  Motivo: usado por `parent_resolver.py` (keyword "cnpj") para casar aditivo/documento
  suplementar ao contrato principal

- [ ] Ação: criar coluna
  Nome exato: `Tipo de Contrato`
  Tipo: Texto
  Opções: —
  Configuração: —
  Obrigatória: SIM
  Motivo: campo livre preenchido por heurística/Gemini (`"tipo de contrato"`)

- [ ] Ação: criar coluna
  Nome exato: `Data do Contrato`
  Tipo: Data
  Opções: —
  Configuração: —
  Obrigatória: SIM
  Motivo: código busca por "data do contrato"

- [ ] Ação: criar coluna
  Nome exato: `Término`
  Tipo: Data
  Opções: —
  Configuração: —
  Obrigatória: SIM
  Motivo: código busca por "término"/"termino"

- [ ] Ação: criar coluna
  Nome exato: `Contrato`
  Tipo: Arquivo (upload) — no Monday é `file`; se o Sunday não tiver upload equivalente
  confirmado, usar `Link` como fallback e registrar a limitação
  Opções: —
  Configuração: —
  Obrigatória: SIM
  Motivo: PDF do contrato assinado; `_find_contrato_column` busca título exato "contrato"

- [ ] Ação: criar coluna
  Nome exato: `Vigência`
  Tipo: Status (customizado)
  Opções: ver tabela abaixo
  Configuração: —
  Obrigatória: SIM
  Motivo: código escreve `"Vigente"` / `"Não Vigente"` (`monday_contracts.py:1569-1574`)

  | Label |
  |---|
  | Vigente |
  | Não Vigente |

- [ ] Ação: criar coluna
  Nome exato: `Observações`
  Tipo: Texto longo
  Opções: —
  Configuração: —
  Obrigatória: NÃO
  Motivo: campo de resumo/observações; não bloqueia leitura, mas é usado quando disponível

- [ ] Ação: confirmar coluna
  Nome exato: `Responsável`
  Tipo: Pessoas
  Opções: —
  Configuração: **já existe como coluna de sistema** (§2) — não recriar, apenas confirmar
  que é essa que o time vai usar em vez de criar uma nova "Responsável" duplicada
  Obrigatória: NÃO

**C) Colunas técnicas (Monday ID / rastreabilidade)**

- [ ] Ação: criar coluna
  Nome exato: `Monday ID`
  Tipo: Texto
  Opções: —
  Configuração: preencher com o `item.id` do Monday durante a migração de dados (Fase 3,
  não agora) — serve só de rastro para auditoria/rollback
  Obrigatória: NÃO (mas fortemente recomendada antes de qualquer migração de dados real)
  Motivo: sem isso, não há como conferir 1:1 os 1.119 itens migrados depois

**D) Colunas que substituem/transformam recursos do Monday**

- Grupos "por Tipo" do Monday (`Contratos B4A`, `Contratos MMKT`, `Contratos Itaro`,
  `Contratos RV BVI`, `Contratos Aurora`, `Contratos Societários`, `Contratos B2B`,
  `Contratos de Câmbio`, `NDA`, `Contratos Influencers (Queens)`, `Procurações`,
  `Contratos Jan`, `Contratos Encerrados`, `Sindicato`, `Políticas Internas`,
  `Ferramentas`, `RH`) **não têm decisão registrada** sobre se, no Sunday, continuam sendo
  **grupos** ou passam a ser uma **coluna de status "Tipo"** (como já é o padrão adotado
  para Controle Assinaturas — ver `controle-sunday-greenfield.md` §5). Isso é uma decisão
  de arquitetura pendente, não vou decidir por você.
  - [ ] Ação: decidir e, se optar por coluna, criar
    Nome exato: `Tipo` (sugestão, alinhado ao padrão já aprovado para o board 77)
    Tipo: Status (customizado)
    Opções: os 16 grupos acima como labels
    Configuração: —
    Obrigatória: NÃO — mas recomendo decidir **antes** da migração de dados

**E) Fórmulas/configurações manuais**: nenhuma fórmula existe no board Contratos do
Monday (confirmado por leitura — só há fórmulas em Processos Judiciais e Processos
Trabalhista, ver §5).

**F) Relações entre boards**: ver §5. Board relation Controle Assinaturas → Contratos
já é o destino confirmado (`Contrato relacionado`, ver Controle 77).

### 4.2 BOARD: Legal - Processos Judiciais
### ID: 84

Origem real: Monday `Processos Judiciais` (id `5343921475`), 155 itens, 6 grupos, 29
colunas — é o board mais complexo dos 8 (inclui a fórmula "saving").

**A) Colunas de sistema já existentes — não recriar**: `Nome`, `Status` (genérico),
`Responsável`, `Data`, `Área`.

**B) Colunas customizadas a criar (mínimo necessário ao pipeline atual —
`juridico/casos.py`)**

- [ ] Ação: criar coluna
  Nome exato: `Número` (ou qualquer título contendo "processo"/"numero"/"nº"/"n")
  Tipo: Texto longo
  Opções: —
  Configuração: **NÃO pode ser `board_relation`** — o código (`monday.py:340-343`)
  ignora colunas `board_relation` ao buscar o CNJ; precisa ser `text`/`long_text`
  Obrigatória: SIM
  Motivo: `_find_cnj_column` é como o pipeline localiza o caso pelo número CNJ

- [ ] Ação: criar coluna
  Nome exato: `Status`
  Tipo: Status (customizado — **não** é o Status de sistema)
  Opções: ver tabela abaixo
  Configuração: —
  Obrigatória: SIM
  Motivo: `_find_status_column(..., "Status")` procura exatamente esse título; código
  escreve `"Encerrado"` em marcos de encerramento

  | Label (Monday atual) |
  |---|
  | Encerrado |
  | Em Andamento |
  | Suspenso |

- [ ] Ação: criar coluna
  Nome exato: `Decisão Judicial`
  Tipo: Status (customizado)
  Opções: ver tabela abaixo
  Configuração: —
  Obrigatória: SIM
  Motivo: `_find_status_column(..., "Decisão Judicial")`; código escreve `"Acordo"` em
  marco de acordo homologado

  | Label (Monday atual) |
  |---|
  | Acordo |
  | Improcedente Favoravel a B4A/MMKT |
  | Condenação B4A/MMKT |
  | Procedente Favoravel B4A/MMKT |
  | Improcedente Desfavoravel B4A/MMKT |

**Demais colunas do Monday real (não exigidas pelo código, mas necessárias para não
perder dado na migração — todas de negócio, sem lógica de pipeline dependente):**

- [ ] Ação: criar coluna
  Nome exato: `Processo relacionado a`
  Tipo: Status
  Opções: `Tributário`, `Consumidor`, `Criminal`, `Administrativo`, `Cível`, `Trabalhista`
  Configuração: —
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Tipo de Ação`
  Tipo: Texto
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Data de Distribuição`
  Tipo: Data
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Sistema`
  Tipo: Status
  Opções: `ESAJ`, `PJE`, `PROJUDI`, `SISTEMA PRÓPRIO`, `EPROC`
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Órgão/JEC`
  Tipo: Status
  Opções: `JEC`, `VC`, `TRF`, `VF`, `JT`
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `TJ`
  Tipo: Status
  Opções: 27 UFs (`TJAC`…`TRT2`) — ver `docs/sunday-fase2-5-monday-snapshot.json` para a
  lista completa exata; não vou recopiar 27 labels aqui manualmente por espaço, mas estão
  todos no snapshot commitado
  Obrigatória: NÃO

- [ ] Ação: criar colunas de arquivo
  Nomes exatos: `Cópia do Processo (CONSUMIDOR)`, `Cópia do Processo (NÃO CONSUMIDOR)`,
  `Documentos SAC`
  Tipo: Arquivo
  Obrigatória: NÃO

- [ ] Ação: criar colunas de data
  Nomes exatos: `Prazo Resposta SAC`, `Prazo Resposta Legal`, `Data ad Audiência`
  Tipo: Data
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Houve Cancelamento de Assinatura?`
  Tipo: Status — Opções: `Não`, `Sim`
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Audiência`
  Tipo: Status — Opções: `Sim`, `Não`
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Local da Audiência`
  Tipo: Localização (se o Sunday não tiver tipo `location`, usar Texto)
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Pessoa responsável pela Audiência`
  Tipo: Pessoas
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `E-mail Metajur/LBZ (se houver)`
  Tipo: E-mail (se não houver tipo `email`, usar Texto)
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Risco`
  Tipo: Status — Opções: `Possível`, `Remoto`, `Provável`
  Obrigatória: NÃO

- [ ] Ação: criar colunas numéricas
  Nomes exatos: `valor da causa`, `Provisão B4A`, `Provisão MMKT`, `Depósito B4A`,
  `Depósito MMKT`, `Pagamentos B4A`, `Pagamentos MMKT`, `condenação`
  Tipo: Número
  Obrigatória: SIM (ver §5 — são a entrada da fórmula `saving`)

- [ ] Ação: criar coluna
  Nome exato: `Movimentações`
  Tipo: Texto longo
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Problema Principal (se aplicável)`
  Tipo: Status — Opções: `Renovação Automática`, `Problemas na Entrega`, `Problemas com
  Cancelamento`, `Problemas no Pagamento`, `Problemas na Experiência`
  Obrigatória: NÃO

**C) Colunas técnicas**: mesma recomendação do board 87 — criar `Monday ID` (texto) antes
da migração de dados, não obrigatória agora.

**D) Grupos observados no Monday** (referência; recriar é opcional/organizacional, não
bloqueia pipeline — **exceção**: o grupo abaixo é usado por código):

- [ ] Ação: criar grupo
  Nome exato: `Processos Consumidores Ativos`
  Obrigatória: SIM (com ressalva) — `DEFAULT_NEW_CASE_GROUP` (`casos.py:48`) usa esse
  título normalizado como grupo de destino ao criar automaticamente um caso novo a partir
  de uma citação. Se este grupo não existir, a criação automática de casos pode falhar ou
  cair num grupo errado quando o backend Sunday for implementado.

- [ ] Ação: criar grupos (opcional, sem lógica de código associada)
  Nomes exatos: `Cível`, `Fiscal Tributário`, `Criminal`, `Administrativo`, `Processos
  Encerrados`
  Obrigatória: NÃO

**E) Fórmulas**: ver §5 — coluna `saving`.

**F) Relações entre boards**: destino de `Prazos → Processos Judiciais` e `Audiências →
Processos Judiciais`. Ver §5.

### 4.3 BOARD: Legal - Processos Trabalhista
### ID: 85

Origem real: Monday `Processos Trabalhista` (id `4443297481`), 24 itens, 2 grupos, 13
colunas. **Não é criado automaticamente pelo pipeline** (`casos.py:236-241`: "Processos
trabalhistas não são criados automaticamente") e **não tem `board_relation`** de/para
nenhum outro board no Monday atual.

**A) Colunas de sistema já existentes**: `Nome`, `Status`, `Responsável`, `Data`, `Área`.

**B) Colunas customizadas a criar**

- [ ] Ação: criar coluna
  Nome exato: `Status`
  Tipo: Status (customizado)
  Opções: `Em andamento`, `Encerrado`
  Configuração: —
  Obrigatória: SIM
  Motivo: `_find_status_column` do módulo KPI/casos também é usado aqui para leitura,
  mesma convenção de título "Status"

- [ ] Ação: criar coluna
  Nome exato: `Tipo de Processo`
  Tipo: Status
  Opções: `Judicial - Tributária`, `Judicial - Trabalhista`, `Judicial - Cível`,
  `Administrativo`, `Criminal`, `Judicial - Consumidor`, `Administrativo - Regulatório`
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Parte Ré`
  Tipo: Texto
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Nº.: de Processo`
  Tipo: Texto
  Obrigatória: SIM (identificação do processo; sem `board_relation` de código, mas é o
  campo-chave para dedup/consulta manual)

- [ ] Ação: criar coluna
  Nome exato: `Local de Origem`
  Tipo: Localização (ou Texto, se o tipo não existir no Sunday)
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Situação Atual`
  Tipo: Texto
  Obrigatória: NÃO

- [ ] Ação: criar colunas numéricas
  Nomes exatos: `Valor da Causa`, `Depósito/Pagamento`, `Provisão`
  Tipo: Número (com prefixo `$`, se o Sunday suportar unidade monetária na coluna)
  Obrigatória: SIM (entrada da fórmula `Saved`, ver §5)

- [ ] Ação: criar coluna
  Nome exato: `Data de Distribuição`
  Tipo: Data
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Risco`
  Tipo: Status — Opções: `Possível`, `Remoto`, `Provável`
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Vara de Origem`
  Tipo: Texto
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Forma de Contratação`
  Tipo: Status — Opções: `Terceirizado`, `CLT`, `PJ`, `Estagiário`, `N/A`
  Obrigatória: NÃO

**C) Colunas técnicas**: `Monday ID` (texto) — recomendada, não obrigatória agora.

**D) Grupos observados**: `Trabalhista Ativo`, `Trabalhista Encerrado` — organizacionais,
sem lógica de código associada.

- [ ] Ação: criar grupos (opcional)
  Nomes exatos: `Trabalhista Ativo`, `Trabalhista Encerrado`
  Obrigatória: NÃO

**E) Fórmulas**: ver §5 — coluna `Saved`.

**F) Relações**: **nenhuma** relação de/para este board foi encontrada no Monday real
(nem em `Prazos`, nem em `Audiências`, nem em `KPI`). Se você esperava uma relação
Prazos/Audiências → Trabalhista, ela **não existe hoje** no Monday — as duas colunas
`board_relation` de Audiências apontam só para `Processos Judiciais` (id `5343921475`).

### 4.4 BOARD: Legal - KPI Processos Consumidores
### ID: 86

Origem real: Monday `KPI - Processos Consumidores` (id `5563754463`), **31 itens**
(confirma a sua instrução: "migrará os 31 itens integralmente" — o número bate
exatamente com a contagem real do board de origem), 5 grupos, 15 colunas. **Decisão
aceita:** migração integral, sem recorte por critério normal.

**A) Colunas de sistema já existentes**: `Nome`, `Status`, `Responsável`, `Data`, `Área`.

**B) Colunas customizadas a criar (mínimo do pipeline —
`juridico/casos.py:458-515`, `casos_consumidor/monday_kpi.py`)**

- [ ] Ação: criar coluna
  Nome exato: `Número do Processo`
  Tipo: Texto longo
  Obrigatória: SIM
  Motivo: `_find_cnj_column` localiza a linha pelo CNJ; sem essa coluna a linha
  correspondente ao processo não é encontrada

- [ ] Ação: criar coluna
  Nome exato: `Resultado`
  Tipo: Status (customizado)
  Opções: ver tabela abaixo
  Obrigatória: SIM
  Motivo: `_find_status_column(..., "Resultado")`; código escreve `"Acordo"` no marco de
  acordo

  | Label (Monday atual) |
  |---|
  | Em andamento |
  | Improcedência |
  | Condenação |
  | Em Recurso (Nosso) |
  | Acordo |

- [ ] Ação: criar coluna
  Nome exato: `Data da Decisão`
  Tipo: Data
  Obrigatória: SIM
  Motivo: `_find_date_column(..., "Data da Decisão")`

- [ ] Ação: criar coluna
  Nome exato: `Situação`
  Tipo: Status (customizado)
  Opções: `Arquivado`, `Ativo`
  Obrigatória: SIM
  Motivo: `_find_status_column(..., "Situação")`; código escreve `"Arquivado"` no marco de
  encerramento

**Demais colunas de negócio (leitura no `monday_kpi.py`, sem escrita pelo pipeline):**

- [ ] Ação: criar coluna
  Nome exato: `Estado`
  Tipo: Status — Opções: as 27 UFs (ver `docs/sunday-fase2-5-monday-snapshot.json`)
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Ré`
  Tipo: Status — Opções: `B4A`, `MMKT`, `B4A & MMKT`
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Data Ajuizamento`
  Tipo: Data
  Obrigatória: NÃO

- [ ] Ação: criar colunas
  Nomes exatos: `Causa 1`, `Causa 2`, `Causa 3`
  Tipo: Status
  Opções (comuns às três): `Renovação Automática`, `Problemas com Pagamento`,
  `Problemas com Entrega`, `Problemas com Cancelamento`, `Problemas na Experiência`
  (os labels variam ligeiramente entre as 3 colunas no Monday atual — ver snapshot para
  o texto exato de cada uma antes de criar, para não normalizar errado)
  Obrigatória: NÃO

- [ ] Ação: criar colunas numéricas
  Nomes exatos: `Valor da Cusa` *(sic — grafia como está no Monday, decisão sua se corrige
  para "Valor da Causa" ao recriar)*, `Provisão`, `Valor da Condenação`, `Valor Pago`,
  `Saving`
  Tipo: Número
  Obrigatória: NÃO (as keywords de leitura `monday_kpi.py:161-173` aceitam variações como
  "condenacao"/"pago"/"resultado"/"decisao", então nomes próximos ainda funcionam, mas
  recomendo manter os nomes reais do Monday para não perder histórico)

**C) Colunas técnicas**: `Monday ID` (texto) — recomendada.

**D) Grupos observados no Monday**: `2023`, `2022`, `2021`, `2020`, `2018` (agrupamento
por ano — não tem lógica de código associada; puramente organizacional/legado).

- [ ] Ação: decidir se recria por ano ou usa uma coluna "Ano" em vez de grupo
  Obrigatória: NÃO — sugestão: não recriar grupos por ano; usar a coluna `Data
  Ajuizamento` com uma view filtrada por ano no Sunday, evitando 5 grupos vazios

**E) Fórmulas**: nenhuma no board KPI (confirmado por leitura).

**F) Relações**: nenhuma `board_relation` encontrada de/para o KPI no Monday atual — o
casamento com o processo é por **texto CNJ**, não por relação de quadro.

### 4.5 BOARD: Legal - Prazos
### ID: 83

Origem real: Monday `Prazos` (id `3961072966`), **880 itens**, 3 grupos, 11 colunas.

**A) Colunas de sistema já existentes**: `Nome`, `Status`, `Responsável`, `Data`, `Área`.

**B) Colunas customizadas a criar (mínimo do pipeline — `juridico/monday.py`)**

- [ ] Ação: criar coluna
  Nome exato: `Número Processo`
  Tipo: Texto
  Obrigatória: SIM
  Motivo: código mapeia por título contendo "numero do processo"/"numero
  processo"/"processo"/"cnj"; **precisa ser texto**, não `board_relation` (o código
  ignora `board_relation` nesse campo)

- [ ] Ação: criar coluna
  Nome exato: `Status`
  Tipo: Status (customizado)
  Opções: ver tabela abaixo
  Obrigatória: SIM
  Motivo: mapeado por `FIELD_PROVIDENCIA`/status geral do prazo

  | Label (Monday atual) |
  |---|
  | Em progresso |
  | Feito |
  | Parado |
  | Não realizada |
  | Não Iniciado |
  | Cancelada |

- [ ] Ação: criar coluna
  Nome exato: `Fatal`
  Tipo: Data
  Obrigatória: SIM
  Motivo: mapeado por `FIELD_DUE_DATE` (keywords "prazo fatal"/"prazo final"/"fatal") —
  é o prazo processual real; a coluna de sistema `Data` genérica não deve ser usada para
  isso, criar uma específica

- [ ] Ação: criar coluna
  Nome exato: `Processo Administrativo`
  Tipo: Status
  Opções: `Não`, `Sim`
  Obrigatória: NÃO (mas o código tem regra de exclusão explícita: títulos contendo
  "administrativo"/"consumidor"/"procon" são **excluídos** do mapeamento de número de
  processo — não confundir esta coluna com `Número Processo`)

- [ ] Ação: criar coluna
  Nome exato: `Pessoa`
  Tipo: Pessoas
  Obrigatória: NÃO (a coluna de sistema `Responsável` cobre o mesmo papel; decidir qual
  usar para não duplicar)

- [ ] Ação: criar coluna
  Nome exato: `Arquivos`
  Tipo: Arquivo
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Controle de tempo`
  Tipo: Time tracking
  Obrigatória: NÃO — **atenção:** o F0.14 listou "criar coluna `time_tracking`" como uma
  das pendências que exigem teste de escrita autorizado (nunca confirmado se a API do
  Sunday aceita esse tipo). Testar a criação manual primeiro; se não for aceito, usar
  Número ou Texto como substituto e registrar a limitação.

**C) `board_relation` (ver §5 para o destino exato)**

- [ ] Ação: criar coluna
  Nome exato: `Processos Consumidores` (nome real no Monday atual; pode manter ou
  renomear para algo mais claro como `Processo relacionado`, já que não há restrição de
  título usada pelo código para essa coluna — ela é localizada por **tipo**
  `board_relation` + `boardIds`, não por título)
  Tipo: `board_relation`
  Configuração: apontar para o board **84 (Legal - Processos Judiciais)**
  Obrigatória: SIM
  Motivo: é como `link_item_to_case` (`casos.py:324-358`) vincula o prazo ao caso; ver §5

**D) Colunas técnicas**: `Monday ID` (texto) — recomendada.

**E) Grupos observados**: `Procon`, `Prazos Processos`, `Prazos Procon's`.

- [ ] Ação: criar grupo
  Nome exato: `Prazos Processos`
  Obrigatória: NÃO (com ressalva) — é o grupo padrão (`DEFAULT_JURIDICO_GROUP_NAME =
  "prazos processos"`) usado ao criar prazos vindos de intimações; se ausente, o env
  `MONDAY_JURIDICO_GROUP_NAME` permite apontar para outro grupo sem mudar código, então
  não é estritamente bloqueante — mas recrie com esse nome para evitar configuração extra

- [ ] Ação: criar grupos (opcional, organizacional)
  Nomes exatos: `Procon`, `Prazos Procon's`
  Obrigatória: NÃO

**F) Fórmulas**: nenhuma no board Prazos.

### 4.6 BOARD: Legal - Audiências
### ID: 72

⚠️ **Este board já tem 9 itens e um grupo extra (`Audiencias Pendentes`) além do grupo
padrão `Itens`.** Alguém já começou a usá-lo manualmente. Confirme com quem criou esses 9
itens antes de adicionar colunas — pode já haver expectativa sobre o schema.

Origem real: Monday `Audiências` (id `4443295406`), 121 itens, 1 grupo, 15 colunas.

**A) Colunas de sistema já existentes**: `Nome`, `Status`, `Responsável`, `Data`, `Área`.

**B) Colunas customizadas a criar**

- [ ] Ação: criar coluna
  Nome exato: `Data`
  Tipo: Data
  Obrigatória: SIM
  Motivo: `_apply_audiencias_date_default` (`monday.py:358-372`) espera uma coluna
  chamada exatamente **"Data"** para a data da audiência — **note que já existe uma
  coluna de sistema chamada "Data"** (§2); confirme qual das duas o time vai considerar
  a data oficial da audiência para não haver ambiguidade quando o backend Sunday for
  implementado (recomendo usar a coluna de sistema e não criar uma segunda "Data")

- [ ] Ação: criar coluna
  Nome exato: `Local`
  Tipo: Localização (ou Texto)
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Presencial ou Virtual`
  Tipo: Status
  Opções: `Presencial`, `Virtual`
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Responsável por comparecer`
  Tipo: Status
  Opções: `Metajur`, `Interno-B4A`, `LBZ`
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Status documentos`
  Tipo: Status
  Opções: `Prontos - pendente Protocolo`, `Já Apresentados`, `A Fazer`
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Link Audiência (se virtual)`
  Tipo: Link
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Processo/Procon`
  Tipo: Status
  Opções: `Procon`, `Processo`, `Outro`
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Status`
  Tipo: Status (customizado — diferente do Status de sistema)
  Opções: `Aguardando`, `Feito`, `Cancelada`, `Em Andamento`, `Encerrado`
  Obrigatória: SIM
  Motivo: código lê/escreve providências por este campo (`FIELD_PROVIDENCIA`/status geral)

- [ ] Ação: criar coluna
  Nome exato: `Número do Processo`
  Tipo: Texto longo
  Obrigatória: SIM
  Motivo: mapeado por `FIELD_PROCESS_NUMBER` (keyword "cnj"/"processo"); **precisa ser
  texto**, nunca `board_relation`

- [ ] Ação: criar coluna
  Nome exato: `Orientações de Audiência`
  Tipo: Texto
  Obrigatória: NÃO

- [ ] Ação: criar colunas (opcionais, sem lógica de código)
  Nomes exatos: `Arquivos` (Arquivo), `Pessoas` (Pessoas), `E-mail` (E-mail/Texto)
  Obrigatória: NÃO

**C) `board_relation`**

- [ ] Ação: criar coluna
  Nome exato: `Processos Judiciais`
  Tipo: `board_relation`
  Configuração: apontar para o board **84 (Legal - Processos Judiciais)**
  Obrigatória: SIM
  Motivo: mesmo mecanismo de vínculo caso↔audiência que existe para Prazos; **atenção:**
  no Monday atual existem **duas colunas** com esse mesmo título e mesmo destino
  (provavelmente uma duplicação legada) — crie **apenas uma** no Sunday, não duplique.

**D) Colunas técnicas**: `Monday ID` (texto) — recomendada.

**E) Grupos**: `Audiências (Procons e Processos)` no Monday; `Itens` + `Audiencias
Pendentes` já existem no Sunday hoje. Decida se consolida em um só grupo ou mantém os
dois que já existem — não crie um terceiro sem necessidade.

**F) Fórmulas**: nenhuma.

### 4.7 BOARD: Legal - Procons
### ID: 82

Origem real: Monday `Procons` (id `4944254220`), 457 itens, 6 grupos, 19 colunas.

**A) Colunas de sistema já existentes**: `Nome`, `Status`, `Responsável`, `Data`, `Área`.

**B) Colunas customizadas a criar (mínimo do pipeline — `monday/mapping.py`)**

- [ ] Ação: criar coluna
  Nome exato: `Procon/Órgão`
  Tipo: Texto
  Obrigatória: SIM
  Motivo: mapeado por `FIELD_STATE` (keywords "estado"/"uf"/"orgao")

- [ ] Ação: criar coluna
  Nome exato: `CIP/FA`
  Tipo: Texto
  Obrigatória: SIM
  Motivo: `FIELD_PROTOCOL` (keywords "cip"/"fa"/"protocolo"/"numero") — chave de dedup por
  protocolo

- [ ] Ação: criar coluna
  Nome exato: `CPF`
  Tipo: Texto longo
  Obrigatória: SIM
  Motivo: `FIELD_CPF` — chave de dedup adicional junto com o protocolo

- [ ] Ação: criar coluna
  Nome exato: `Status`
  Tipo: Status (customizado)
  Opções: `Baixado`, `Respondido`
  Obrigatória: SIM
  Motivo: `FIELD_STATUS`; filtro de "fechado" usa keyword "respondido"/"baixado" no texto
  do status

- [ ] Ação: criar coluna
  Nome exato: `Origem`
  Tipo: Status (customizado)
  Opções: `Men's "Loja"`, `Glam "Clube"`, `Glam "Loja"`, `Men's "Clube"`
  Obrigatória: SIM (usada para segmentar a origem da reclamação)

- [ ] Ação: criar colunas de data
  Nomes exatos: `Data da Reclamação`, `Prazo resposta SAC`, `Prazo Resposta Jurídico`,
  `Data da Resposta Legal/Baixa`
  Tipo: Data
  Obrigatória: SIM
  Motivo: `FIELD_COMPLAINT_DATE`/`FIELD_SAC_DEADLINE`/`FIELD_LEGAL_DEADLINE`/
  `FIELD_RESPONSE_DATE` — são os prazos de SLA que o pipeline monitora

- [ ] Ação: criar colunas de link
  Nomes exatos: `Resposta Completa`, `Resumo Resposta`, `PDF Unificado`
  Tipo: Link
  Obrigatória: SIM
  Motivo: usadas por `update_elaborated_response_links`; os títulos exatos aparecem
  hardcoded na mensagem de erro do cliente Monday (`client.py:946-947`) — manter esses
  três títulos exatos

- [ ] Ação: criar coluna
  Nome exato: `Notificação Procon`
  Tipo: Arquivo
  Obrigatória: SIM
  Motivo: `FIELD_PDF_URL`

- [ ] Ação: criar coluna
  Nome exato: `Docs SAC`
  Tipo: Arquivo
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Observações/Histórico`
  Tipo: Texto longo
  Obrigatória: NÃO

- [ ] Ação: criar colunas
  Nomes exatos: `Causa 1`, `Causa 2 (se houver)`, `Causa 3 (se houver)`
  Tipo: Status
  Opções: `Problemas com Cancelamento`, `Renovação Automática`, `Problemas na
  experiência`/`Problemas na Experiência`, `Problemas no pagamento`, `Problemas com
  entrega` (grafias variam ligeiramente entre as 3 colunas no Monday atual — usar o texto
  exato de cada uma, ver snapshot)
  Obrigatória: SIM (pelo menos "Causa 1") — mapeado por `FIELD_CAUSE`

- [ ] Ação: criar coluna
  Nome exato: `Gerou Processo Administrativo`
  Tipo: Status — Opções: `Sim`, `Não`
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Prazo Resposta Processo Administrativo`
  Tipo: Data
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Processo Administrativo Respondido`
  Tipo: Status — Opções: `Sim`, `Não`, `Cancelado`
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Houve Cancelamento de Assinatura?`
  Tipo: Status — Opções: `Não`, `Sim`
  Obrigatória: NÃO

- [ ] Ação: criar coluna
  Nome exato: `Já está na black list?`
  Tipo: Status — Opções: `Não`, `Sim`, `Em análise`
  Obrigatória: NÃO

**C) Colunas técnicas**: `Monday ID` (texto) — recomendada.

**D) Grupos observados**: `Pendentes de Resposta` (default do pipeline, `client.py:36`
— **recriar com este nome exato é recomendado**, embora configurável por
`MONDAY_BOARD_NAME`/env), `Processos Administrativos` (usado por
`MONDAY_PA_GROUP_NAME`), `2023`/`2024`/`2025`/`2026` (arquivo por ano, sem lógica de
código).

- [ ] Ação: criar grupo
  Nome exato: `Pendentes de Resposta`
  Obrigatória: NÃO (configurável por env, mas recrie para evitar trabalho extra depois)

- [ ] Ação: criar grupo
  Nome exato: `Processos Administrativos`
  Obrigatória: NÃO

**E) Fórmulas**: nenhuma no board Procons.

**F) Relações**: nenhuma `board_relation` no Monday atual para este board.

### 4.8 BOARD: Legal - Controle de Assinaturas
### ID: 77 (nome real: "Legal - Controle de Assinaturas - Jan & Luciano")

Esta é a única seção onde existe uma decisão arquitetural **aprovada** por escrito
(`docs/controle-sunday-greenfield.md`, status `SUNDAY_SCHEMA_READY_FOR_APPROVAL`). O
Monday legado (`Controle Assinaturas Contratos`, id `5301515799`, 1.607 itens) fica
**congelado** — não é migrado, não recebe mais sync. O modelo novo é **1 item = 1
documento Autentique** (não 2 linhas Jan/Luciano como no Monday).

**A) Colunas de sistema já existentes — não recriar**: `Nome`, `Status` (genérico —
**não usar para status de negócio**), `Responsável`, `Data`, `Área`.

**B) Colunas customizadas a criar** (schema v1 aprovado, `controle-sunday-greenfield.md`
§4):

- [ ] Ação: criar coluna
  Nome exato: `Autentique ID`
  Tipo: Texto
  Obrigatória: SIM
  Motivo: chave de identidade única para UPSERT — nunca usar `(id, track)`

- [ ] Ação: criar coluna
  Nome exato: `Link Autentique`
  Tipo: Link
  Obrigatória: SIM
  Motivo: abrir o documento na origem

- [ ] Ação: criar coluna
  Nome exato: `Tipo`
  Tipo: Status (customizado)
  Opções: ver tabela abaixo
  Obrigatória: NÃO
  Motivo: categorização contratual; roteamento futuro para Contratos (87)

  | Label |
  |---|
  | Contratos B4A |
  | Contratos MMKT |
  | Contratos Itaro |
  | Contratos RV BVI |
  | Contratos Aurora |
  | Contratos Societários |
  | Contratos B2B |
  | NDA |
  | Contratos Influencers (Queens) |
  | Contratos Jan |
  | Pedidos Marcas Próprias |
  | RH |

  *(explicitamente excluído: `Contratos de Câmbio` — só existe no board Contratos, não
  no Controle, por decisão já registrada no doc de origem)*

- [ ] Ação: criar coluna
  Nome exato: `Status Jan`
  Tipo: Status (customizado)
  Opções: ver tabela abaixo
  Obrigatória: SIM
  Motivo: fila operacional do Jan — **nunca** usar como gatilho de conclusão

  | Label | Key sugerida |
  |---|---|
  | Aguardando Jan | `aguardando_jan` |
  | Jan assinou | `jan_assinou` |
  | Não requerido | `nao_requerido` |

- [ ] Ação: criar coluna
  Nome exato: `Status Luciano`
  Tipo: Status (customizado)
  Opções: ver tabela abaixo
  Obrigatória: SIM
  Motivo: fila operacional do Luciano — **nunca** usar como gatilho de conclusão

  | Label | Key sugerida |
  |---|---|
  | Aguardando Luciano | `aguardando_luciano` |
  | Luciano assinou | `luciano_assinou` |
  | Não requerido | `nao_requerido` |

- [ ] Ação: criar coluna
  Nome exato: `Status Geral`
  Tipo: Status (customizado)
  Opções: ver tabela abaixo
  Obrigatória: SIM
  Motivo: **único** gatilho de conclusão para automações futuras — sempre calculado pela
  integração, nunca editado manualmente (o doc de origem determina que o próximo sync
  sobrescreve qualquer edição manual)

  | Label | Key sugerida |
  |---|---|
  | Aguardando assinatura | `aguardando_assinatura` |
  | Parcialmente assinado | `parcialmente_assinado` |
  | Assinado | `assinado` |
  | Revisão manual | `revisao_manual` |

- [ ] Ação: criar coluna
  Nome exato: `Scope`
  Tipo: Status (customizado)
  Opções: `eligible`, `manual_review`
  Obrigatória: SIM
  Motivo: `ineligible` nunca gera item; `manual_review` é visível e separado

- [ ] Ação: criar coluna
  Nome exato: `Motivo da revisão`
  Tipo: Texto
  Obrigatória: NÃO (condicional — só preenchida quando `Scope = manual_review` ou status
  terminal do Autentique)

- [ ] Ação: criar coluna
  Nome exato: `Última sincronização`
  Tipo: Data (com hora, se o Sunday suportar) ou Texto ISO-8601
  Obrigatória: SIM
  Motivo: auditoria operacional do sync

**Colunas explicitamente excluídas do v1** (decisão já registrada — não crie):
Data criação Autentique, Fornecedor/contraparte, Responsável dedicado (as filas já são
cobertas por Status Jan/Luciano + views), `board_relation` para Contratos no schema
inicial (fica para a automação pós-`Assinado`, ver §5), Versão de sync/hash.

**C) Colunas técnicas**: `Autentique ID` já cobre a chave técnica (ver B). Não é
necessário um "Monday ID" aqui — este board é greenfield (não migra os 1.607 itens do
Monday legado).

**D) Colunas que substituem/transformam recursos do Monday**: o modelo dual-track (2
linhas Jan/Luciano + coluna "Quem Assina") do Monday **não é recriado**. As 3 colunas de
status (Jan/Luciano/Geral) no **mesmo item** substituem isso.

**E) Fórmulas**: nenhuma — `Status Geral` é **derivado por código**, não por fórmula
nativa do Sunday.

**F) Relações**: `board_relation` para Contratos **fica de fora do schema v1** por
decisão já registrada (será criada pela automação pós-`Assinado`, não no schema inicial).
Ver §5 mesmo assim para o destino já confirmado, caso decida antecipar.

**Grupos a criar/configurar** (nomes exatos — ver seção dedicada abaixo, "Controle — Board
77").

---

## 5. Relações entre boards (`board_relation`)

Confirmação: os **IDs de destino agora existem de fato** (84 e 85 foram criados nesta
rodada), então as relações abaixo já podem ser configuradas com o ID correto — mas
**nada foi configurado**, isso é só a especificação para você aplicar manualmente.

### Relação 1 — Prazos → Processos Judiciais

- Board origem: Legal - Prazos
- ID origem: **83**
- Nome exato da coluna: `Processos Consumidores` (nome real no Monday; livre para
  renomear, pois a coluna é localizada por tipo, não por título)
- Tipo: `board_relation`
- Board destino: Legal - Processos Judiciais
- ID destino: **84**
- Configuração esperada / `source_board_id`: **84**
- Cardinalidade: 1 prazo → 1 caso (`allowMultipleItems` não usado no Monday atual —
  manter 1:1 no Sunday)

### Relação 2 — Audiências → Processos Judiciais

- Board origem: Legal - Audiências
- ID origem: **72**
- Nome exato da coluna: `Processos Judiciais`
- Tipo: `board_relation`
- Board destino: Legal - Processos Judiciais
- ID destino: **84**
- Configuração esperada / `source_board_id`: **84**
- Cardinalidade: 1 audiência → 1 caso. **Não** existe, hoje, uma relação equivalente para
  Processos Trabalhista (85) — confirmado por leitura, nenhuma coluna aponta para lá.

### Relação 3 — Controle de Assinaturas → Contratos

- Board origem: Legal - Controle de Assinaturas
- ID origem: **77**
- Nome exato da coluna: `Contrato relacionado` (nome real no Monday atual)
- Tipo: `board_relation`
- Board destino: Legal - Contratos
- ID destino: **87**
- Configuração esperada / `source_board_id`: **87**
- Cardinalidade: `allowMultipleItems: false` no Monday — manter 1:1
- **Atenção:** por decisão já registrada em `controle-sunday-greenfield.md`, esta coluna
  **não faz parte do schema v1** do board 77 — é responsabilidade de uma automação futura
  pós-`Assinado`, não do schema inicial. Só crie esta coluna agora se você decidir
  antecipar essa automação; não é obrigatória para o preflight.

### Quarta relação — não encontrada

Procurei por qualquer outra coluna `board_relation` ativa nos 8 boards de origem no
Monday (leitura completa de todas as colunas dos 8 boards). **Não existe uma quarta
relação real.** Encontrei apenas um resíduo: uma coluna `board_relation` no Controle
Assinaturas chamada `"link to Notificações Carol - Assinaturas Jan"` com
`boardIds: []` (vazio) — ou seja, **não aponta para nenhum board hoje**; é lixo/legado,
não uma relação ativa. Não recomendo recriá-la sem entender primeiro para que ela servia.

### Aviso sobre `source_board_id` incorreto

Conforme o F0.14, a API do Sunday **não valida** se o `source_board_id` de uma
`board_relation` está correto — ela grava o valor mesmo assim, sem garantir a
integridade semântica. Ao criar cada uma das 3 colunas acima, **confirme visualmente**
no seletor de quadro do Sunday que o quadro de destino escolhido é exatamente o board 84
(ou 87), e não um board com nome parecido (ex.: não confundir com "Processos Trabalhista"
85 ou com o sandbox "SANDBOX - API SUNDAY - RELATION"). Um `source_board_id` errado aqui
vai silenciosamente persistir e só vai aparecer como erro no dry-run futuro.

---

## 6. Contratos (87) — subitens/hierarquia para os 104 aditivos

**Confirmado por leitura**, sem ambiguidade: `GET /boards/87` retornou
`"capabilities": {"subitems": false, ...}`. **Subitens não estão habilitados hoje** no
board Legal - Contratos.

Como não consegui, via API, confirmar **onde exatamente** essa opção é ativada na
interface do Sunday (o endpoint só informa o estado atual, não o caminho de configuração,
e este token não tem acesso de leitura a `capabilities`/configurações administrativas
do board), aqui está onde procurar manualmente:

- [ ] Ação: abrir o board "Legal - Contratos" no app do Sunday
- [ ] Ação: procurar no menu de configurações do quadro (geralmente um ícone de
  engrenagem ou os "···" no canto superior direito do quadro) por uma opção chamada
  "Subitens", "Hierarquia" ou "Gerenciar subitens"
- [ ] Ação, alternativa: ao adicionar uma nova coluna ("+" no final das colunas ou botão
  "Adicionar coluna"), procurar por um tipo de coluna chamado "Subitens" — em ferramentas
  deste tipo, adicionar essa coluna geralmente é o que habilita a hierarquia no board
- [ ] Ação: depois de habilitar (se encontrar a opção), **não crie nenhum subitem real
  ainda** — apenas confirme que a opção existe e ficou disponível; a criação dos 104
  aditivos como subitens é tarefa de uma fase de migração de dados, não desta etapa
- [ ] Ação: se não encontrar a opção em nenhum menu, volte e me diga — pode ser uma
  limitação de plano/workspace que precisa ser resolvida com o administrador do Sunday
  (que teria acesso a `admin_scopes`, que este token não tem)

---

## 7. Área (coluna estrutural)

| Board | Área |
|---|---|
| 72 — Legal - Audiências | IGNORAR |
| 77 — Legal - Controle de Assinaturas | IGNORAR |
| 82 — Legal - Procons | IGNORAR |
| 83 — Legal - Prazos | IGNORAR |
| 84 — Legal - Processos Judiciais | IGNORAR |
| 85 — Legal - Processos Trabalhista | IGNORAR |
| 86 — Legal - KPI Processos Consumidores | IGNORAR |
| 87 — Legal - Contratos | IGNORAR |

Confirmado por leitura nos 8 boards: `Área` é `key=area`, `dropdown`, `is_system=true`,
`options=[]`, sem valor default. Conforme F0.14, criação/edição de item funciona sem
informar Área. **Não excluir, não recriar, não renomear** em nenhum board — em nenhum
board há uma decisão registrada de "UTILIZAR" com valor específico.

---

## 8. Fórmulas

Encontrei, por leitura real do Monday, exatamente **duas** colunas de fórmula nos 8
boards de origem — batem com sua afirmação de "duas fórmulas classificadas como
configuração manual":

### Fórmula 1

- Board: Legal - Processos Judiciais (84)
- Nome exato: `saving`
- Origem Monday: coluna `formula` com expressão `{n_meros6}-{n_meros1}`
  - `n_meros1` = coluna `condenação` (confirmado — o id bate exatamente)
  - `n_meros6` = **não bate com nenhum id de coluna atual** do board (o id mais próximo
    é `n_meros6__1`, título `Provisão MMKT`) — isso sugere que a fórmula referencia uma
    coluna que foi renomeada/duplicada ao longo do tempo no Monday e o id original ficou
    "solto". **Não vou adivinhar** qual é a intenção real; confirme com quem mantém o
    board antes de recriar.
- Configuração equivalente recomendada no Sunday: se o Sunday tiver um tipo de coluna
  `formula` equivalente, recriar como `<Provisão MMKT ou o campo correto> - condenação`
  (depende da confirmação acima). **Se o Sunday não tiver coluna de fórmula** (não
  testado no F0.14 — o teste C do F0.14 cobriu `board_relation`/status/Área, não
  `formula`), o fallback é criar `saving` como coluna de **Número** comum e calcular o
  valor manualmente ou por automação externa.
- Dependências: as colunas numéricas de entrada (`condenação` e a Provisão correta)
  precisam existir **antes** de criar a fórmula.
- Ordem: criar **depois** das demais colunas numéricas do board 84 (ver checklist do
  board 84, seção B).

### Fórmula 2

- Board: Legal - Processos Trabalhista (85)
- Nome exato: `Saved`
- Origem Monday: coluna `formula` com expressão `{n_meros}-{n_meros1}-{n_meros9}` =
  `Valor da Causa` − `Depósito/Pagamento` − `Provisão` (os três ids batem exatamente com
  os títulos atuais — sem ambiguidade aqui)
- Configuração equivalente recomendada no Sunday: se houver tipo `formula`, recriar
  exatamente como `Valor da Causa - Depósito/Pagamento - Provisão`. Sem tipo `formula`
  confirmado, mesmo fallback do item anterior (coluna Número comum).
- Dependências: `Valor da Causa`, `Depósito/Pagamento` e `Provisão` precisam existir
  antes.
- Ordem: criar **depois** das três colunas numéricas do board 85 (ver checklist do board
  85, seção B).

**Pendência que bloqueia a decisão final:** nenhum microteste anterior (F0.14 ou os
scripts de retest) testou se `type: "formula"` é aceito pela API/UI do Sunday. Recomendo
testar a criação manual de **uma** coluna de fórmula simples em um board sandbox (69 ou
70) antes de decidir o caminho definitivo para os boards 84/85.

---

## 9. Controle de Assinaturas (77) — grupos

Grupos derivados da arquitetura **aprovada** em `controle-sunday-greenfield.md` §6 (não
do Monday — o Monday usa um modelo dual-track diferente que está sendo **substituído**,
não copiado). Se você esperava os nomes dos grupos do Monday (`Contratos Pendentes de
Assinatura Jan`, `Contratos Pendentes de Assinatura Luciano`, `Pendente Fornecedor`,
`Assinados`, `Recusado`), **não é isso que o schema aprovado pede** — o doc explicitamente
move as filas Jan/Luciano de "grupos" para "colunas de status no mesmo item", exatamente
para não duplicar o documento em duas linhas.

- [ ] Ação: criar grupo
  Nome exato: `Em assinatura`
  Obrigatória: NÃO (grupos são "conveniência visual opcional" no doc aprovado — quem
  decide o estado é a coluna `Status Geral`, não o grupo)
  Motivo: itens com `Scope = eligible` e `Status Geral` ≠ `Assinado`

- [ ] Ação: criar grupo
  Nome exato: `Revisão necessária`
  Obrigatória: NÃO
  Motivo: itens com `Scope = manual_review` ou `Status Geral = Revisão manual`

- [ ] Ação: criar grupo
  Nome exato: `Assinados`
  Obrigatória: NÃO
  Motivo: arquivo visual de itens com `Status Geral = Assinado`

O doc aprovado recomenda **views** como mecanismo principal para as filas operacionais
(Jan, Luciano, parcial, revisão, assinados) — ver `controle-sunday-greenfield.md` §7 para
os filtros sugeridos de cada view, caso você queira configurá-las também nesta rodada
(não pedido explicitamente neste checklist, mas relevante).

---

## 10. Ordem exata de execução recomendada

1. **Board 77 primeiro** — confirmar visualmente na lista do workspace 22 que o board com
   o nome real "Legal - Controle de Assinaturas - Jan & Luciano" é de fato o board que
   você quer usar como "Legal - Controle de Assinaturas" (ver §2, mismatch de nome). Só
   prossiga com o resto depois de confirmar isso mentalmente — não precisa renomear.
2. Em **cada um dos 8 boards**, nesta ordem por board:
   a. Criar as colunas **customizadas não-relação** primeiro (Seção B de cada
      checklist), na ordem em que aparecem — colunas de texto/data/número antes de
      qualquer coluna que dependa delas.
   b. Configurar as **opções de status customizado** dentro de cada coluna de status
      recém-criada, usando exatamente os labels das tabelas fornecidas (não usar
      fuzzy match, não inventar labels novos).
   c. Criar/organizar os **grupos**, quando marcados como obrigatórios (só o grupo
      `Processos Consumidores Ativos` no board 84 e, com ressalva, `Prazos Processos`
      no board 83; os demais são opcionais).
3. Só depois de **todos os 8 boards** terem suas colunas não-relação prontas, criar as
   **3 colunas `board_relation`** (Seção 5) — nesta ordem específica, porque cada uma
   depende do board de destino já existir e estar estável:
   a. Prazos (83) → Processos Judiciais (84)
   b. Audiências (72) → Processos Judiciais (84)
   c. (Opcional, decisão sua) Controle (77) → Contratos (87) — só se decidir antecipar a
      automação pós-assinatura
4. Testar manualmente, em **um único item de teste por relação** (pode reaproveitar os
   sandboxes 80/81 em vez de criar itens de teste nos boards reais), que o seletor de
   quadro de destino realmente aponta para o board certo (84, não 85; 87, não outro) —
   ver aviso de `source_board_id` incorreto na Seção 5.
5. Resolver a pendência das **duas fórmulas** (Seção 8) — testar se o Sunday aceita coluna
   tipo fórmula em um board sandbox antes de decidir o caminho definitivo para 84/85. Isso
   pode ficar para o final, sem bloquear o resto.
6. Verificar/ativar **subitens no board 87** (Seção 6), sem criar nenhum subitem real.
7. **Não tocar em `Área`** em nenhum board (Seção 7).
8. Só então: me avise para eu fazer a **validação por leitura + `--refresh-sunday` +
   dry-run final** — que é a próxima etapa combinada, ainda sem Fase 3.

---

## Pendências que ficam explicitamente abertas (não decidi por você)

1. Matching de usuários real (bloqueado por permissão de API + falta da lista de 28
   identidades no repositório).
2. Fórmula 1 do board 84 (`saving`): qual coluna real corresponde a `{n_meros6}`.
3. Se o Sunday aceita coluna tipo `formula` (não testado).
4. Se "Contratos por Tipo" no board 87 deve ser modelado como grupos (como está hoje no
   Monday) ou como uma coluna `Tipo` (como já foi decidido para o board 77).
5. Onde exatamente, na UI do Sunday, se habilita subitens (não pude confirmar via API).
6. O nome real do board 77 ter um sufixo extra — se isso é aceitável ou se você quer que
   eu trate como um board diferente do que a Fase 2 original pretendia (apesar de "não
   renomear nada").
