"""Tipos e erros compartilhados pelos clientes de portais de tribunais."""

from __future__ import annotations

from dataclasses import dataclass, field

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_DEFAULT_TIMEOUT_MS = 45000


class PortalError(RuntimeError):
    """Falha ao consultar o portal do tribunal."""


class PortalRequiresInteraction(PortalError):
    """Portal exigiu captcha/2FA/certificado — precisa de humano."""


class PortalUnsupported(PortalError):
    """Sistema do tribunal ainda sem scraper (ex.: PJe com captcha obrigatório)."""


@dataclass(frozen=True)
class ProcessContent:
    process_number: str
    source: str
    classe: str | None = None
    assunto: str | None = None
    situacao: str | None = None
    movements: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        header = " — ".join(
            part for part in (self.classe, self.assunto, self.situacao) if part
        )
        lines = [f"Teor do processo {self.process_number} (fonte: {self.source})"]
        if header:
            lines.append(header)
        if self.movements:
            lines.append("Movimentações:")
            lines.extend(f"- {movement}" for movement in self.movements)
        return "\n".join(lines)


def dedupe_movements(rows: list[str], *, limit: int = 20) -> list[str]:
    """Normaliza e remove movimentações repetidas, preservando a ordem."""
    movements: list[str] = []
    seen: set[str] = set()
    for row in rows:
        text = " ".join(row.split())[:300]
        if text and text not in seen:
            seen.add(text)
            movements.append(text)
    return movements[:limit]
