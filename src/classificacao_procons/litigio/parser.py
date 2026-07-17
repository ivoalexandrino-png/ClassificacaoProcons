"""Análise de intimações: extrai prazo, audiência e classifica a providência.

As regras abaixo são heurísticas de triagem (palavras-chave e padrões de data
comuns em publicações do PJe/e-SAJ) para decidir, de forma conservadora, se
uma intimação exige alguma ação do jurídico. Elas **não substituem a leitura
da certidão pelo advogado responsável** — em caso de dúvida, o item é
classificado como `INDEFINIDA` e marcado como `requer_atencao=True`, para
nunca deixar de aparecer no Monday por falta de reconhecimento automático.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Final

from bs4 import BeautifulSoup

from classificacao_procons.litigio.models import Intimacao, Providencia, ProvidenciaTipo

_PRAZO_DIAS_PATTERN: Final = re.compile(
    r"prazo\s+de\s+(\d{1,3})\s*\(?[^)]{0,20}?\)?\s*dias",
    re.IGNORECASE,
)
_DATA_PATTERN: Final = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
_AUDIENCIA_JANELA_CARACTERES: Final = 160

_AUDIENCIA_KEYWORDS: Final = ("audiencia", "audiencia designada", "sessao de julgamento")
_RECURSO_KEYWORDS: Final = ("recurso", "apelacao", "agravo", "embargos", "contrarrazoes")
_MANIFESTACAO_KEYWORDS: Final = (
    "manifest",
    "impugnacao",
    "impugnar",
    "querendo",
    "querer",
    "especificar provas",
    "réplica",
    "replica",
)
_PAGAMENTO_KEYWORDS: Final = (
    "deposito",
    "pagamento",
    "guia de recolhimento",
    "custas",
    "honorarios",
    "condenacao",
)
_CIENCIA_KEYWORDS: Final = ("tomar ciencia", "ciencia do", "ato ordinatorio", "dar-se por citado")

# Comunicações puramente informativas: sem prazo/audiência, não exigem providência.
_SEM_ACAO_TIPOS_DOCUMENTO: Final = ("certidao", "ato ordinatorio")


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _plain_text(html_or_text: str) -> str:
    soup = BeautifulSoup(html_or_text or "", "html.parser")
    return soup.get_text(separator=" ")


def _extract_prazo_dias(texto_normalizado: str) -> int | None:
    match = _PRAZO_DIAS_PATTERN.search(texto_normalizado)
    if not match:
        return None
    return int(match.group(1))


def _extract_data_audiencia(texto: str, texto_normalizado: str) -> date | None:
    for keyword in _AUDIENCIA_KEYWORDS:
        index = texto_normalizado.find(keyword)
        if index < 0:
            continue
        janela = texto[
            index : index + len(keyword) + _AUDIENCIA_JANELA_CARACTERES
        ]
        match = _DATA_PATTERN.search(janela)
        if not match:
            continue
        day, month, year = (int(part) for part in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None


def _classificar_tipo(
    *,
    texto_normalizado: str,
    tipo_documento_normalizado: str,
    tem_audiencia: bool,
    tem_prazo: bool,
) -> ProvidenciaTipo:
    if tem_audiencia:
        return ProvidenciaTipo.AUDIENCIA
    if any(keyword in texto_normalizado for keyword in _RECURSO_KEYWORDS):
        return ProvidenciaTipo.RECURSO
    if any(keyword in texto_normalizado for keyword in _PAGAMENTO_KEYWORDS):
        return ProvidenciaTipo.PAGAMENTO_DEPOSITO
    if any(keyword in texto_normalizado for keyword in _MANIFESTACAO_KEYWORDS):
        return ProvidenciaTipo.MANIFESTACAO
    if tem_prazo:
        return ProvidenciaTipo.MANIFESTACAO
    if any(keyword in texto_normalizado for keyword in _CIENCIA_KEYWORDS):
        return ProvidenciaTipo.CIENCIA
    if tipo_documento_normalizado in _SEM_ACAO_TIPOS_DOCUMENTO:
        return ProvidenciaTipo.CIENCIA
    return ProvidenciaTipo.INDEFINIDA


def _requer_atencao(*, tipo: ProvidenciaTipo, cancelada: bool) -> bool:
    if cancelada:
        return False
    return tipo != ProvidenciaTipo.CIENCIA


def _descricao(*, tipo: ProvidenciaTipo, intimacao: Intimacao) -> str:
    if intimacao.cancelada:
        return f"Publicação cancelada pelo tribunal ({intimacao.motivo_cancelamento})."
    base = intimacao.tipo_documento or intimacao.tipo_comunicacao or "Comunicação"
    descricoes = {
        ProvidenciaTipo.AUDIENCIA: f"{base}: audiência designada.",
        ProvidenciaTipo.RECURSO: f"{base}: prazo para recurso.",
        ProvidenciaTipo.PAGAMENTO_DEPOSITO: f"{base}: providência de pagamento/depósito.",
        ProvidenciaTipo.MANIFESTACAO: f"{base}: manifestação necessária.",
        ProvidenciaTipo.CIENCIA: f"{base}: apenas ciência, sem ação exigida.",
        ProvidenciaTipo.INDEFINIDA: f"{base}: revisar manualmente (tipo não identificado).",
    }
    return descricoes[tipo]


def analisar_intimacao(intimacao: Intimacao) -> Providencia:
    """Classifica a providência exigida por uma intimação e extrai prazo/audiência."""
    texto_plano = _plain_text(intimacao.texto)
    texto_normalizado = _normalize(texto_plano)
    tipo_documento_normalizado = _normalize(intimacao.tipo_documento)

    prazo_dias = None if intimacao.cancelada else _extract_prazo_dias(texto_normalizado)
    data_audiencia = (
        None if intimacao.cancelada else _extract_data_audiencia(texto_plano, texto_normalizado)
    )

    tipo = _classificar_tipo(
        texto_normalizado=texto_normalizado,
        tipo_documento_normalizado=tipo_documento_normalizado,
        tem_audiencia=data_audiencia is not None,
        tem_prazo=prazo_dias is not None,
    )

    prazo_data = None
    if prazo_dias is not None:
        prazo_data = _add_calendar_days(intimacao.data_disponibilizacao, prazo_dias)

    return Providencia(
        intimacao_id=intimacao.id,
        numero_processo=intimacao.numero_processo,
        tipo=tipo,
        descricao=_descricao(tipo=tipo, intimacao=intimacao),
        requer_atencao=_requer_atencao(tipo=tipo, cancelada=intimacao.cancelada),
        prazo_dias=prazo_dias,
        prazo_data=prazo_data,
        data_audiencia=data_audiencia,
    )


def _add_calendar_days(start: date, dias: int) -> date:
    """Soma dias corridos ao prazo. Não aplica suspensões/feriados forenses:
    trate `prazo_data` como estimativa e confirme o prazo processual real
    antes de qualquer decisão com efeito prático."""
    return date.fromordinal(start.toordinal() + dias)


def analisar_texto_bruto(
    *,
    texto: str,
    data_disponibilizacao: date | None = None,
    tipo_documento: str = "",
    tipo_comunicacao: str = "",
    numero_processo: str = "",
) -> Providencia:
    """Atalho para testar a heurística com um texto solto, sem depender do DJEN."""
    intimacao = Intimacao(
        id=0,
        hash="",
        numero_processo=numero_processo,
        numero_processo_formatado=numero_processo,
        tribunal="",
        tipo_comunicacao=tipo_comunicacao,
        tipo_documento=tipo_documento,
        orgao="",
        classe_processual="",
        data_disponibilizacao=data_disponibilizacao or datetime.now().date(),
        texto=texto,
    )
    return analisar_intimacao(intimacao)
