"""Testes da classificação de providências."""

from datetime import date, datetime

from classificacao_procons.juridico.models import IntimacaoEmail
from classificacao_procons.juridico.providencia import (
    STATUS_A_PROVIDENCIAR,
    STATUS_ACOMPANHAR,
    classify_providencia,
)


def _intimacao(**overrides: object) -> IntimacaoEmail:
    base = {
        "message_id": "m1",
        "subject": "Intimação",
        "sender": "tribunal@x.jus.br",
        "received_at": datetime(2026, 7, 17, 9, 0),
        "process_number": "1023456-78.2026.8.26.0100",
        "tribunal": "TJSP",
        "vara": "3ª Vara Cível",
        "publication_date": date(2026, 7, 17),
    }
    base.update(overrides)
    return IntimacaoEmail(**base)  # type: ignore[arg-type]


class TestClassifyProvidencia:
    def test_should_flag_hearing_as_audiencia(self) -> None:
        prov = classify_providencia(_intimacao(hearing_at=datetime(2026, 8, 15, 14, 0)))
        assert prov.tipo == "Audiência"
        assert prov.hearing_at == datetime(2026, 8, 15, 14, 0)
        assert prov.requires_action is True

    def test_should_apply_default_prazo_for_citacao(self) -> None:
        prov = classify_providencia(
            _intimacao(movement_type="Citação", body_excerpt="Citação para contestar"),
        )
        assert prov.tipo == "Contestar"
        # 15 dias úteis a partir da publicação 17/07 -> 07/08
        assert prov.prazo_final == date(2026, 8, 7)

    def test_should_use_explicit_prazo_over_default(self) -> None:
        prov = classify_providencia(
            _intimacao(
                movement_type="Embargos",
                body_excerpt="Embargos de declaração",
                prazo_dias=30,
            ),
        )
        # prazo explícito 30 sobrepõe o padrão (5) do movimento
        assert prov.prazo_final == date(2026, 8, 28)

    def test_should_mark_informative_movement_as_acompanhar(self) -> None:
        prov = classify_providencia(
            _intimacao(
                movement_type=None,
                body_excerpt="Certidão de juntada de petição aos autos.",
            ),
        )
        assert prov.requires_action is False
        assert prov.status == STATUS_ACOMPANHAR

    def test_should_classify_sentenca_as_recurso(self) -> None:
        prov = classify_providencia(
            _intimacao(movement_type="Sentença", body_excerpt="sentença proferida"),
        )
        assert prov.tipo == "Analisar recurso"
        assert prov.status == STATUS_A_PROVIDENCIAR

    def test_should_respect_holidays_in_prazo(self) -> None:
        prov = classify_providencia(
            _intimacao(movement_type="Citação", body_excerpt="Citação"),
            holidays=[date(2026, 7, 20)],
        )
        assert prov.prazo_final == date(2026, 8, 10)
