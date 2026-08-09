"""Testes da CLI do radar de editais."""

import json

from classificacao_procons.radar.cli import main


def _write_snapshot(path) -> None:
    path.write_text(
        json.dumps(
            {
                "captured_at": "2026-08-09T09:00:00",
                "editais": [
                    {
                        "source_key": "cnpq",
                        "source_name": "CNPq",
                        "title": "Edital de pesquisa em Direito",
                        "url": "https://cnpq.br/edital-1",
                        "areas": ["direito"],
                        "status": "aberto",
                    },
                    {
                        "source_key": "cnpq",
                        "source_name": "CNPq",
                        "title": "Edital de engenharia aeroespacial",
                        "url": "https://cnpq.br/aero",
                        "status": "aberto",
                    },
                ],
            },
        ),
        encoding="utf-8",
    )


def test_sources_should_list_registry(capsys) -> None:
    exit_code = main(["sources", "--scope", "internacional"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload
    assert all(item["scope"] == "internacional" for item in payload)


def test_scan_should_return_relevant_matches(tmp_path, capsys) -> None:
    snapshot = tmp_path / "snap.json"
    _write_snapshot(snapshot)

    exit_code = main(["scan", "--snapshot", str(snapshot)])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["match_count"] == 1
    assert payload["matches"][0]["matched_areas"] == ["direito"]


def test_scan_should_filter_by_area(tmp_path, capsys) -> None:
    snapshot = tmp_path / "snap.json"
    _write_snapshot(snapshot)

    exit_code = main(["scan", "--snapshot", str(snapshot), "--areas", "saude"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["match_count"] == 0


def test_scan_should_error_on_invalid_json(tmp_path, capsys) -> None:
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{not json", encoding="utf-8")

    exit_code = main(["scan", "--snapshot", str(snapshot)])

    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


def test_check_dry_run_with_snapshot_should_not_send(tmp_path, capsys) -> None:
    snapshot = tmp_path / "snap.json"
    _write_snapshot(snapshot)

    exit_code = main(
        [
            "check",
            "--snapshot",
            str(snapshot),
            "--to",
            "pesquisa@uni.br",
            "--dry-run",
            "--state-path",
            str(tmp_path / "state.json"),
        ],
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run"
    assert payload["alert_sent"] is False
    assert payload["new_match_count"] == 1
