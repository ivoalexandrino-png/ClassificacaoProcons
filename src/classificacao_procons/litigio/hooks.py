"""Pontos de extensão para os futuros agentes de litígio.

Este agente de monitoramento (intimação → providência → Monday) é o
primeiro de três, pensados para operar em conjunto:

1. **Monitoramento** (este módulo): lê intimações do DJEN, decide se exigem
   providência e mantém o Monday atualizado com prazos e audiências.
2. **Elaboração e protocolo de peças** (futuro, inexistente): deve reagir a
   eventos com `tipo_providencia` em `{MANIFESTACAO, RECURSO}` para redigir
   e protocolar a peça correspondente.
3. **Relatórios contingenciais** (futuro, inexistente): deve consumir todos
   os eventos (inclusive `CIENCIA`) para manter o relatório de andamentos,
   depósitos e provisões atualizado.

Nenhum dos dois agentes futuros existe ainda, então esta versão não integra
com eles diretamente. O que existe é o ponto de extensão abaixo: um registro
de *handlers* em processo, chamado para cada `EventoProcesso` gerado pelo
pipeline, mais um log append-only em disco (`data/litigio-eventos.jsonl`)
que qualquer processo externo pode "tailar" para o mesmo efeito sem
acoplamento direto ao código Python.

Quando os agentes existirem, a forma mais simples de conectá-los é:

```python
from classificacao_procons.litigio.hooks import registrar_handler

def enviar_para_agente_de_pecas(evento):
    ...

registrar_handler(enviar_para_agente_de_pecas)
```
"""

from __future__ import annotations

from collections.abc import Callable

from classificacao_procons.litigio.models import EventoProcesso

ProvidenciaHandler = Callable[[EventoProcesso], None]

_handlers: list[ProvidenciaHandler] = []


def registrar_handler(handler: ProvidenciaHandler) -> None:
    """Registra um handler a ser chamado para cada evento processado."""
    _handlers.append(handler)


def remover_handler(handler: ProvidenciaHandler) -> None:
    if handler in _handlers:
        _handlers.remove(handler)


def limpar_handlers() -> None:
    _handlers.clear()


def notificar_handlers(evento: EventoProcesso) -> None:
    """Chama todos os handlers registrados. Erros de um handler não impedem
    os demais nem o restante do pipeline."""
    for handler in list(_handlers):
        try:
            handler(evento)
        except Exception:
            # Handler de terceiro (futuro agente); um erro ali não deve
            # interromper o processamento dos demais eventos/handlers.
            continue
