"""Quais filas Jan/Luciano o Controle deve ter, conforme signatários no Autentique."""

from __future__ import annotations

from classificacao_procons.contratos.autentique.client import AutentiqueDocumentSummary
from classificacao_procons.contratos.signer_identity import find_jan_signer, find_luciano_signer

ControleTrackName = str  # "jan" | "luciano"


def document_required_controle_tracks(
    document: AutentiqueDocumentSummary,
) -> frozenset[ControleTrackName]:
    """Retorna ``jan`` e/ou ``luciano`` somente se houver signatário interno correspondente."""
    tracks: set[ControleTrackName] = set()
    if find_jan_signer(document.signatures):
        tracks.add("jan")
    if find_luciano_signer(document.signatures):
        tracks.add("luciano")
    if tracks:
        return frozenset(tracks)
    if not document.signatures:
        return frozenset({"jan", "luciano"})
    return frozenset()


def track_required_for_document(
    document: AutentiqueDocumentSummary,
    *,
    track: ControleTrackName,
) -> bool:
    return track in document_required_controle_tracks(document)
