"""Rótulos da coluna Status no Monday vs constantes do sync Controle."""

import pytest

from classificacao_procons.contratos.controle_monday_status import (
    CONTROLE_STATUS_LABELS_REQUIRED,
    find_missing_controle_status_labels,
    load_controle_status_labels_report,
    parse_status_column_labels_from_settings,
)
from classificacao_procons.monday.client import get_api_token_from_env


class TestControleStatusLabelParsing:
    def test_should_parse_status_labels_from_settings_str(self) -> None:
        import json

        settings = json.dumps(
            {
                "labels": {
                    "0": "Aguardando Assinatura",
                    "1": "Assinado",
                    "2": "Recusado",
                    "3": "Bloqueado - aguardando providencia",
                    "4": "Aguardando outros",
                },
            },
            ensure_ascii=False,
        )
        parsed = parse_status_column_labels_from_settings(settings)
        assert "Bloqueado - aguardando providencia" in parsed
        assert "Recusado" in parsed

    def test_should_detect_missing_labels_case_insensitive(self) -> None:
        monday = ("Aguardando assinatura", "Assinado", "Aguardando outros")
        missing = find_missing_controle_status_labels(monday)
        assert "Recusado" in missing
        assert "Bloqueado - aguardando providencia" in missing

    def test_should_pass_when_all_required_labels_present(self) -> None:
        missing = find_missing_controle_status_labels(CONTROLE_STATUS_LABELS_REQUIRED)
        assert missing == ()


    def test_snapshot_should_include_all_required_labels(self) -> None:
        from classificacao_procons.contratos.controle_monday_status import (
            MONDAY_CONTROLE_STATUS_LABELS_SNAPSHOT,
        )

        missing = find_missing_controle_status_labels(MONDAY_CONTROLE_STATUS_LABELS_SNAPSHOT)
        assert missing == ()


class TestControleStatusLabelsLiveMonday:
    def test_should_match_controle_status_labels_on_live_board(self) -> None:
        token = get_api_token_from_env()
        if not token:
            pytest.skip("MONDAY_API_TOKEN ausente")

        report = load_controle_status_labels_report(api_token=token)
        assert report.status_column_id
        assert report.monday_labels, "coluna Status sem rótulos no Monday"

        if report.missing_required_labels:
            pytest.fail(
                "Rótulos ausentes no Monday (coluna Status): "
                f"{list(report.missing_required_labels)}. "
                f"Disponíveis no quadro: {list(report.monday_labels)}. "
                "Ajuste constants.py ou crie os status no Monday.",
            )
