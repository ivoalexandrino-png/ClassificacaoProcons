"""Testes do roteador de portais por sistema do DataJud."""

from unittest.mock import patch

import pytest

from classificacao_procons.juridico.acessos import PortalCredential
from classificacao_procons.juridico.portais import router
from classificacao_procons.juridico.portais.base import (
    PortalUnsupported,
    ProcessContent,
)

TJSP = "1002605-16.2025.8.26.0198"
TJPR_PROJUDI = "0001206-20.2026.8.16.0195"
TRT2 = "1000817-79.2026.5.02.0511"


def _content(source: str) -> ProcessContent:
    return ProcessContent(process_number="x", source=source, movements=["mov"])


class TestRouter:
    def test_should_route_saj_to_esaj_public(self) -> None:
        with patch.object(
            router.esaj, "fetch_process_content_public", return_value=_content("e-SAJ"),
        ) as esaj_call:
            result = router.fetch_process_content(TJSP, sistema="SAJ")
        assert result.source == "e-SAJ"
        esaj_call.assert_called_once()

    def test_should_route_projudi_with_credential(self) -> None:
        cred = PortalCredential("TJ-PR", "PROJUDI", "login", "senha")
        with (
            patch.object(router, "get_tribunal_credential", return_value=cred),
            patch.object(
                router.projudi, "fetch_process_content", return_value=_content("Projudi TJPR"),
            ) as projudi_call,
        ):
            result = router.fetch_process_content(
                TJPR_PROJUDI, sistema="Projudi", tribunal="TJPR",
            )
        assert result.source == "Projudi TJPR"
        assert projudi_call.call_args.kwargs["tribunal_acronym"] == "TJPR"

    def test_should_raise_unsupported_when_projudi_without_credential(self) -> None:
        with patch.object(router, "get_tribunal_credential", return_value=None):
            with pytest.raises(PortalUnsupported, match="sem credencial"):
                router.fetch_process_content(TJPR_PROJUDI, sistema="Projudi", tribunal="TJPR")

    def test_should_route_pje_to_public_consultation(self) -> None:
        with patch.object(
            router.pje, "fetch_process_content_public", return_value=_content("PJe TRT2"),
        ) as pje_call:
            result = router.fetch_process_content(TRT2, sistema="PJe")
        assert result.source == "PJe TRT2"
        assert pje_call.call_args.kwargs["alias"] == "trt2"

    def test_should_raise_unsupported_for_unknown_system(self) -> None:
        with pytest.raises(PortalUnsupported, match="ainda sem scraper"):
            router.fetch_process_content(TJSP, sistema="Sistema Exótico", tribunal="XX")
