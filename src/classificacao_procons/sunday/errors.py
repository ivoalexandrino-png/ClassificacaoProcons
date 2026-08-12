"""Exceções do cliente Sunday.

As mensagens nunca incluem token, headers de autenticação ou URL completa com
credenciais — apenas método, caminho, status HTTP e a mensagem de negócio da API.
"""

from __future__ import annotations


class SundayError(RuntimeError):
    """Erro base do cliente Sunday."""

    def __init__(self, message: str, *, status: int | None = None, path: str | None = None):
        super().__init__(message)
        self.status = status
        self.path = path


class SundayConfigError(SundayError):
    """Configuração ausente/inválida (ex.: SUNDAY_API_TOKEN não definido)."""


class SundayAuthError(SundayError):
    """401 — token ausente, inválido ou revogado."""


class SundayForbiddenError(SundayError):
    """403 — rota exclusiva de sessão, escopo de token ausente ou recurso inacessível."""


class SundayNotFoundError(SundayError):
    """404 — recurso ou rota inexistente."""


class SundayValidationError(SundayError):
    """400 — payload inválido ou regra de negócio (ex.: coluna de sistema via /values)."""


class SundayConflictError(SundayError):
    """409/422 — conflito ou erro de negócio."""


class SundayHTTPError(SundayError):
    """Demais erros HTTP ou falha de rede."""


class SundayRelationIntegrityError(SundayError):
    """Relação rejeitada pelo client: board-alvo diverge do source_board_id da coluna.

    A API do Sunday NÃO valida o value de board_relation contra a configuração da
    coluna (confirmado empiricamente na F0.15) — esta validação é responsabilidade
    nossa e acontece ANTES de qualquer chamada de escrita.
    """


class SundayVerifyError(SundayError):
    """Escrita respondeu 2xx mas a releitura não devolveu o valor esperado.

    Protege contra o comportamento observado de HTTP 200 com alteração ignorada em
    silêncio (ex.: `status`, `group_id` e `assignee_user_ids` no PATCH genérico).
    """


def _business_message(body: object) -> str:
    if isinstance(body, dict):
        message = body.get("message")
        if isinstance(message, list):
            return "; ".join(str(part) for part in message)
        if message:
            return str(message)
    if isinstance(body, str) and body.strip():
        return body.strip()[:200]
    return "sem detalhe"


def error_for_status(status: int, method: str, path: str, body: object) -> SundayError:
    """Constrói a exceção adequada para um status HTTP de erro (sem dados sensíveis)."""
    detail = _business_message(body)
    message = f"Sunday API {method} {path} -> HTTP {status}: {detail}"
    if status == 401:
        return SundayAuthError(message, status=status, path=path)
    if status == 403:
        return SundayForbiddenError(message, status=status, path=path)
    if status == 404:
        return SundayNotFoundError(message, status=status, path=path)
    if status == 400:
        return SundayValidationError(message, status=status, path=path)
    if status in (409, 422):
        return SundayConflictError(message, status=status, path=path)
    return SundayHTTPError(message, status=status, path=path)
