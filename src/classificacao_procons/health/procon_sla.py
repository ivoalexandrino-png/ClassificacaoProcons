"""Detecção de atraso: e-mails não lidos e automação GitHub parada."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime

from classificacao_procons.email.gmail import GmailClientError, GmailProconFetcher

DEFAULT_GITHUB_OWNER = "ivoalexandrino-png"
DEFAULT_GITHUB_REPO = "ClassificacaoProcons"
DEFAULT_WORKFLOW_FILE = "procon-hourly.yml"


class ProconSlaError(RuntimeError):
    """Falha ao consultar SLA."""


@dataclass(frozen=True)
class StaleUnreadNotification:
    message_id: str
    subject: str
    protocol_number: str | None
    source_id: str
    notification_type: str
    received_at: datetime
    age_minutes: int


@dataclass(frozen=True)
class ProconSlaReport:
    checked_at: datetime
    max_age_minutes: int
    stale_notifications: tuple[StaleUnreadNotification, ...]
    unread_scanned: int


@dataclass(frozen=True)
class WorkflowFreshnessReport:
    workflow_file: str
    last_run_created_at: datetime | None
    last_run_status: str | None
    last_run_conclusion: str | None
    age_minutes: int | None
    max_age_minutes: int
    is_stale: bool


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _age_minutes(*, received_at: datetime, now: datetime) -> int:
    delta = _as_utc(now) - _as_utc(received_at)
    return max(0, int(delta.total_seconds() // 60))


def build_procon_sla_report(
    *,
    token_path: str,
    max_age_minutes: int,
    max_results: int = 50,
    now: datetime | None = None,
) -> ProconSlaReport:
    """Lista não lidos do Gmail e sinaliza os mais antigos que o SLA."""
    if max_age_minutes < 1:
        raise ProconSlaError("max_age_minutes deve ser >= 1.")

    checked_at = _as_utc(now or datetime.now(tz=UTC))
    fetcher = GmailProconFetcher.from_credentials(
        credentials_path="",
        token_path=token_path,
    )
    try:
        notifications = fetcher.list_unread_notifications(max_results=max_results)
    except GmailClientError as exc:
        raise ProconSlaError(str(exc)) from exc

    stale: list[StaleUnreadNotification] = []
    for notification in notifications:
        if notification.notification_type == "interacao_consumidor":
            continue
        age = _age_minutes(received_at=notification.received_at, now=checked_at)
        if age < max_age_minutes:
            continue
        stale.append(
            StaleUnreadNotification(
                message_id=notification.message_id,
                subject=notification.subject,
                protocol_number=notification.protocol_number,
                source_id=notification.source_id,
                notification_type=notification.notification_type,
                received_at=_as_utc(notification.received_at),
                age_minutes=age,
            ),
        )

    stale.sort(key=lambda item: item.age_minutes, reverse=True)
    return ProconSlaReport(
        checked_at=checked_at,
        max_age_minutes=max_age_minutes,
        stale_notifications=tuple(stale),
        unread_scanned=len(notifications),
    )


def _parse_github_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(UTC)


def check_github_workflow_freshness(
    *,
    token: str,
    max_age_minutes: int,
    workflow_file: str = DEFAULT_WORKFLOW_FILE,
    owner: str | None = None,
    repo: str | None = None,
    now: datetime | None = None,
) -> WorkflowFreshnessReport:
    """Verifica se houve run recente do workflow Procon automation."""
    if max_age_minutes < 1:
        raise ProconSlaError("max_age_minutes deve ser >= 1.")
    if not token.strip():
        raise ProconSlaError("Token GitHub ausente para checagem do workflow.")

    repo_owner = owner or os.environ.get("GITHUB_REPOSITORY_OWNER", DEFAULT_GITHUB_OWNER)
    repo_name = repo or _repository_name_from_env() or DEFAULT_GITHUB_REPO
    checked_at = _as_utc(now or datetime.now(tz=UTC))

    url = (
        f"https://api.github.com/repos/{repo_owner}/{repo_name}/actions/workflows/"
        f"{workflow_file}/runs?per_page=1&branch=main"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token.strip()}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ProconSlaError(f"GitHub API HTTP {exc.code} ao listar runs.") from exc
    except urllib.error.URLError as exc:
        raise ProconSlaError(f"GitHub API indisponível: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise ProconSlaError("GitHub API retornou JSON inválido.") from exc

    runs = payload.get("workflow_runs", [])
    if not runs:
        return WorkflowFreshnessReport(
            workflow_file=workflow_file,
            last_run_created_at=None,
            last_run_status=None,
            last_run_conclusion=None,
            age_minutes=None,
            max_age_minutes=max_age_minutes,
            is_stale=True,
        )

    last = runs[0]
    created_at = _parse_github_timestamp(str(last["created_at"]))
    age = _age_minutes(received_at=created_at, now=checked_at)
    status = str(last.get("status") or "")
    conclusion = str(last.get("conclusion") or "")
    successful = status == "completed" and conclusion == "success"
    is_stale = (not successful) or age >= max_age_minutes

    return WorkflowFreshnessReport(
        workflow_file=workflow_file,
        last_run_created_at=created_at,
        last_run_status=status,
        last_run_conclusion=conclusion,
        age_minutes=age,
        max_age_minutes=max_age_minutes,
        is_stale=is_stale,
    )


def _repository_name_from_env() -> str | None:
    full = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if "/" not in full:
        return None
    return full.split("/", 1)[1]
