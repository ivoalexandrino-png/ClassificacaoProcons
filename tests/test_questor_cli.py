"""Testes da CLI do Questor."""

import json

from classificacao_procons.questor.cli import main


def _write_snapshot(path, *, situacao: str) -> None:
    path.write_text(
        json.dumps(
            {
                "empresa": "Beauty For All",
                "cnpj": "12345678000199",
                "captured_at": "2026-08-08T09:00:00",
                "certidoes": [{"orgao": "FGTS/CRF", "situacao": situacao}],
            },
        ),
        encoding="utf-8",
    )


def test_analyze_should_return_1_and_print_issues_when_critical(tmp_path, capsys) -> None:
    snapshot = tmp_path / "snap.json"
    _write_snapshot(snapshot, situacao="positiva")

    exit_code = main(["analyze", "--snapshot", str(snapshot)])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["critical_count"] == 1
    assert payload["issues"][0]["kind"] == "certidao_positiva"


def test_analyze_should_return_0_when_regular(tmp_path, capsys) -> None:
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(
        json.dumps(
            {
                "captured_at": "2026-08-08T09:00:00",
                "certidoes": [
                    {"orgao": "FGTS/CRF", "situacao": "negativa", "data_validade": "31/12/2026"},
                ],
            },
        ),
        encoding="utf-8",
    )

    exit_code = main(["analyze", "--snapshot", str(snapshot)])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["has_problems"] is False


def test_analyze_should_error_on_invalid_json(tmp_path, capsys) -> None:
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{not json", encoding="utf-8")

    exit_code = main(["analyze", "--snapshot", str(snapshot)])

    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


def test_check_dry_run_with_snapshot_should_not_send(tmp_path, capsys) -> None:
    snapshot = tmp_path / "snap.json"
    _write_snapshot(snapshot, situacao="positiva")

    exit_code = main(
        [
            "check",
            "--snapshot",
            str(snapshot),
            "--to",
            "fiscal@b4a.com,contabil@b4a.com",
            "--dry-run",
            "--state-path",
            str(tmp_path / "state.json"),
        ],
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run"
    assert payload["alert_sent"] is False
    assert payload["new_issue_count"] == 1
