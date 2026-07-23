"""Testes de detecção de documento totalmente assinado."""

from __future__ import annotations

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
    is_document_fully_signed,
)


def _signer(*, email: str, signed: bool) -> AutentiqueSigner:
    return AutentiqueSigner(
        public_id="pub",
        name=email,
        email=email,
        short_link=None,
        signed_at="2026-07-22T10:00:00Z" if signed else None,
    )


class TestIsDocumentFullySigned:
    def test_should_return_false_when_signatures_pending(self) -> None:
        signatures = (
            _signer(email="a@example.com", signed=True),
            _signer(email="b@example.com", signed=False),
        )

        assert is_document_fully_signed(
            signed_pdf_url="https://example.com/partial.pdf",
            signatures=signatures,
        ) is False

    def test_should_return_true_when_all_signatures_complete(self) -> None:
        signatures = (
            _signer(email="a@example.com", signed=True),
            _signer(email="b@example.com", signed=True),
        )

        assert is_document_fully_signed(
            signed_pdf_url="https://example.com/signed.pdf",
            signatures=signatures,
        ) is True

    def test_should_use_signed_pdf_when_signatures_missing(self) -> None:
        assert is_document_fully_signed(
            signed_pdf_url="https://example.com/signed.pdf",
            signatures=(),
        ) is True

    def test_summary_should_match_helper(self) -> None:
        document = AutentiqueDocumentSummary(
            document_id="doc-1",
            name="Contrato",
            created_at=None,
            signed_pdf_url="https://example.com/partial.pdf",
            signatures=(
                _signer(email="matheus@example.com", signed=True),
                _signer(email="b4a@example.com", signed=False),
            ),
        )

        assert document.is_fully_signed is False
