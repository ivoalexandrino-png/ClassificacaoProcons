"""Agente jurídico: intimações → andamento processual → Monday (prazos e audiências).

Este subpacote implementa um agente para o jurídico interno que:

1. Recebe intimações/pushes por e-mail (Gmail).
2. Identifica o processo, o tipo de movimento e extrai prazos e audiências.
3. (Opcional) consulta o sistema de andamento processual para enriquecer os dados.
4. Determina a providência necessária e registra no Monday para controle de
   prazos e audiências.

O agente foi desenhado para, no futuro, delegar trabalho a dois outros agentes
(ainda inexistentes) através das interfaces em :mod:`classificacao_procons.juridico.agents`:

- Elaboração e protocolo de peças processuais.
- Atualização de relatórios contingenciais (andamentos, depósitos, provisões).
"""

from classificacao_procons.juridico.models import (
    Andamento,
    IntimacaoEmail,
    ProcessoJudicial,
    Providencia,
    RegistroJuridicoResult,
)

__all__ = [
    "Andamento",
    "IntimacaoEmail",
    "Providencia",
    "ProcessoJudicial",
    "RegistroJuridicoResult",
]
