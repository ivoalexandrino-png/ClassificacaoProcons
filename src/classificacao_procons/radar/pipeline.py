"""Fluxo do radar: coleta → análise → digest por e-mail.

O snapshot pode vir do coletor (``feeds.collect_snapshot``) ou ser injetado
(arquivo JSON no CLI, ou fixture nos testes). A análise é offline; o digest só
dispara com editais novos (dedup por ``dedup_key`` em estado persistido),
evitando reavisar o mesmo edital a cada execução.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from classificacao_procons.google_auth import GoogleAuthError, has_gmail_send_access
from classificacao_procons.radar.analise import analyze_snapshot
from classificacao_procons.radar.models import (
    CORE_AREAS,
    Area,
    RadarAnalysis,
    RadarMatch,
    RadarSnapshot,
    Scope,
)
from classificacao_procons.radar.notifier import (
    GmailSender,
    GmailSenderError,
    build_digest_email,
)
from classificacao_procons.radar.sources import get_sources

DEFAULT_STATE_PATH = Path("data/radar-alerted.json")

SnapshotProvider = Callable[["RadarPipelineOptions"], RadarSnapshot]


class RadarPipelineError(RuntimeError):
    """Erro geral no pipeline do radar de editais."""


@dataclass(frozen=True)
class RadarPipelineOptions:
    recipients: tuple[str, ...] = ()
    cc: tuple[str, ...] = ()
    sender: str | None = None
    interest_areas: tuple[Area, ...] = CORE_AREAS
    scope: Scope | None = None
    source_keys: tuple[str, ...] | None = None
    include_closed: bool = False
    dry_run: bool = False
    only_new: bool = True
    state_path: Path = DEFAULT_STATE_PATH
    token_path: str = "credentials/gmail-token.json"


@dataclass(frozen=True)
class RadarPipelineResult:
    status: str
    analysis: RadarAnalysis | None = None
    new_matches: tuple[RadarMatch, ...] = field(default_factory=tuple)
    alert_sent: bool = False
    alert_recipients: tuple[str, ...] = ()
    message_id: str | None = None
    error: str | None = None


def _load_alerted_keys(state_path: Path) -> set[str]:
    if not state_path.exists():
        return set()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(key) for key in data.get("alerted_keys", [])}


def _save_alerted_keys(state_path: Path, keys: set[str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"alerted_keys": sorted(keys)}
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_snapshot(
    options: RadarPipelineOptions,
    *,
    snapshot: RadarSnapshot | None,
    snapshot_provider: SnapshotProvider | None,
) -> RadarSnapshot:
    if snapshot is not None:
        return snapshot
    provider = snapshot_provider or _default_feed_provider
    return provider(options)


def _default_feed_provider(options: RadarPipelineOptions) -> RadarSnapshot:
    # Import tardio: só é necessário para a coleta real (acesso à rede).
    from classificacao_procons.radar.feeds import collect_snapshot

    sources = get_sources(scope=options.scope, keys=options.source_keys)
    if not sources:
        raise RadarPipelineError(
            "Nenhuma fonte de fomento selecionada para a coleta.",
        )
    return collect_snapshot(sources)


def run_radar_check(
    options: RadarPipelineOptions,
    *,
    snapshot: RadarSnapshot | None = None,
    snapshot_provider: SnapshotProvider | None = None,
) -> RadarPipelineResult:
    """Coleta o snapshot, analisa e envia o digest se houver edital novo."""
    resolved = _resolve_snapshot(
        options,
        snapshot=snapshot,
        snapshot_provider=snapshot_provider,
    )
    analysis = analyze_snapshot(
        resolved,
        interest_areas=options.interest_areas,
        include_closed=options.include_closed,
    )

    alerted_keys = _load_alerted_keys(options.state_path)
    if options.only_new:
        new_matches = tuple(
            match for match in analysis.matches if match.dedup_key not in alerted_keys
        )
    else:
        new_matches = analysis.matches

    if not analysis.has_matches:
        return RadarPipelineResult(status="ok", analysis=analysis)

    if not new_matches:
        return RadarPipelineResult(status="no_new_matches", analysis=analysis)

    if options.dry_run:
        return RadarPipelineResult(
            status="dry_run",
            analysis=analysis,
            new_matches=new_matches,
            alert_recipients=tuple(options.recipients),
        )

    if not options.recipients:
        raise RadarPipelineError("Nenhum destinatário configurado para o digest do radar.")

    if not has_gmail_send_access(options.token_path):
        raise RadarPipelineError(
            "Token Gmail sem permissão de envio. Reautorize com: procon-email auth",
        )

    digest_analysis = RadarAnalysis(
        snapshot=resolved,
        matches=new_matches,
        interest_areas=options.interest_areas,
    )
    email = build_digest_email(
        digest_analysis,
        to=list(options.recipients),
        cc=list(options.cc),
    )
    try:
        sender = GmailSender.from_credentials(token_path=options.token_path)
        message_id = sender.send(email, sender=options.sender)
    except (GmailSenderError, GoogleAuthError) as exc:
        raise RadarPipelineError(str(exc)) from exc

    _save_alerted_keys(
        options.state_path,
        alerted_keys | {match.dedup_key for match in new_matches},
    )

    return RadarPipelineResult(
        status="alert_sent",
        analysis=analysis,
        new_matches=new_matches,
        alert_sent=True,
        alert_recipients=tuple(options.recipients),
        message_id=message_id,
    )
