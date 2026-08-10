"""Quais filas Jan/Luciano o Controle deve ter, conforme signatários no Autentique."""

from __future__ import annotations

from dataclasses import dataclass

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.signer_identity import find_jan_signer, find_luciano_signer

ControleTrackName = str  # "jan" | "luciano"


@dataclass(frozen=True)
class InternalSignersDetected:
    jan: bool
    luciano: bool
    jan_signer: AutentiqueSigner | None
    luciano_signer: AutentiqueSigner | None


def detect_internal_signers(
    document: AutentiqueDocumentSummary,
) -> InternalSignersDetected:
    jan = find_jan_signer(document.signatures)
    luc = find_luciano_signer(document.signatures)
    return InternalSignersDetected(
        jan=jan is not None,
        luciano=luc is not None,
        jan_signer=jan,
        luciano_signer=luc,
    )


def resolve_expected_tracks(
    document: AutentiqueDocumentSummary,
) -> frozenset[ControleTrackName]:
    """Única fonte de verdade: quais filas Monday devem existir para este documento."""
    return document_required_controle_tracks(document)


def document_required_controle_tracks(
    document: AutentiqueDocumentSummary,
) -> frozenset[ControleTrackName]:
    """Retorna ``jan`` e/ou ``luciano`` somente se houver signatário interno correspondente."""
    detected = detect_internal_signers(document)
    tracks: set[ControleTrackName] = set()
    if detected.jan:
        tracks.add("jan")
    if detected.luciano:
        tracks.add("luciano")
    return frozenset(tracks)


def track_required_for_document(
    document: AutentiqueDocumentSummary,
    *,
    track: ControleTrackName,
) -> bool:
    return track in document_required_controle_tracks(document)
