"""Chaves idempotentes para create_item no Controle."""

import pytest

from classificacao_procons.contratos.controle_idempotency import (
    build_controle_create_idempotency_key,
)


class TestControleCreateIdempotencyKey:
    def test_should_build_stable_key(self) -> None:
        assert build_controle_create_idempotency_key(
            autentique_document_id="ABC-123",
            track="jan",
        ) == "controle:abc-123:jan"

    def test_should_reject_invalid_track(self) -> None:
        with pytest.raises(ValueError):
            build_controle_create_idempotency_key(
                autentique_document_id="x",
                track="other",
            )
