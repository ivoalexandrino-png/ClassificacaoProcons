# Mapeamento — PA 1681159/2026 (Silvia) vs CIP 1624924/2026

## Regra de negócio (validada)

| Aspecto | Decisão |
|---------|---------|
| Monday | **Item separado** no grupo **Processos Administrativos**, protocolo **1681159/2026** |
| Drive | **Mesma pasta** da CIP **1624924/2026** se for a **mesma consumidora e mesmos fatos** |
| CIP anterior | Permanece no grupo Pendentes / histórico; item `12455122069` |
| Interação consumidor | Update no item do **PA** (1681159), não na CIP |
| Resposta no portal | Já feita; automação só registra timeline |

## Identidade

- **SILVIA RAFAELA DE PAULA CAMARGO** — CPF 446.685.528-52  
- CIP: **1624924/2026** (defesa 08/07, interação na CIP)  
- PA: **1681159/2026** — conversão 22/07/2026; nº administrativo **35.001.003.26.1681159**  
- Prazo PA (portal): **03/08/2026**

## Por que 1681159 não existia no Monday

O board só tinha a linha da **CIP**. O PA é outro protocolo de atendimento; e-mails de abertura/interação **não trazem código de acesso** (login gov.br). A automação antiga só atualizava colunas de PA **no item da CIP**, não criava linha no grupo de PA.

## Verificação “mesmo caso”

1. **Portal** (lista PA): CPF/nome batem com item `12455122069`.  
2. **Heurística** (sem portal): CPF único no board, “Gerou PA” = Sim, data da reclamação **anterior** à abertura do PA (`pa_conversion_heuristic`); fallback se houver **um único** item com Gerou PA = Sim.
3. Se no futuro houver **duas** CIPs com PA aberto para o mesmo CPF, revisão manual.

## E-mails mapeados

| Tipo | Assunto | Parser |
|------|---------|--------|
| Reclamação (login usuário/senha) | Notificação de emissão de **Reclamação** | `require_access_code=False`, protocolo no corpo |
| PA aberto | Processo Administrativo Aberto: 35…1681159 | Protocolo `1681159/ano` pelo último segmento do PA |
| Interação | Interação do Consumidor | Protocolo `1681159/2026` no corpo |

## Implementação

- `pa_standalone_registry.ensure_pa_monday_item_for_protocol`  
- `interaction_pipeline`: se não achar item por protocolo, tenta cadastrar PA + update  
- `docs/procon-portal-procurador.md` — sessão gov.br opcional  
