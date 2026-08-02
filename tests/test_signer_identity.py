"""Testes de identidade de signatários B4A no Autentique."""

from classificacao_procons.contratos.autentique.client import AutentiqueSigner
from classificacao_procons.contratos.signer_identity import (
    email_matches_jan,
    email_matches_luciano,
    find_jan_signer,
    find_luciano_signer,
    name_matches_jan,
    name_matches_luciano,
    signer_is_jan,
    signer_is_luciano,
)


class TestSignerIdentity:
    def test_should_recognize_jan_by_assinador_display_name(self) -> None:
        signer = AutentiqueSigner(
            public_id="1",
            name="Assinador",
            email=None,
            short_link=None,
            signed_at=None,
        )

        assert signer_is_jan(signer) is True
        assert find_jan_signer((signer,)) is signer

    def test_should_recognize_jan_by_jan_riehle_name(self) -> None:
        assert name_matches_jan("Jan Riehle") is True
        signer = AutentiqueSigner(
            public_id="1",
            name="Jan Riehle",
            email=None,
            short_link=None,
            signed_at=None,
        )
        assert signer_is_jan(signer) is True

    def test_should_recognize_jan_by_assinador_email_variations(self) -> None:
        assert email_matches_jan("assinador@b4a.com.br") is True
        assert email_matches_jan("Assinador@b4a.com.br") is True

    def test_should_recognize_luciano_by_beauty_for_all_display_name(self) -> None:
        signer = AutentiqueSigner(
            public_id="2",
            name="Beauty For All",
            email=None,
            short_link=None,
            signed_at=None,
        )

        assert signer_is_luciano(signer) is True
        assert find_luciano_signer((signer,)) is signer

    def test_should_recognize_luciano_by_name_luciano(self) -> None:
        assert name_matches_luciano("Luciano") is True
        signer = AutentiqueSigner(
            public_id="2",
            name="Luciano",
            email=None,
            short_link=None,
            signed_at=None,
        )
        assert signer_is_luciano(signer) is True

    def test_should_recognize_luciano_by_juridico_email_variations(self) -> None:
        assert email_matches_luciano("juridico@b4a.com.br") is True
        assert email_matches_luciano("juridico@b4a.co") is True

    def test_should_not_confuse_assinador_with_luciano(self) -> None:
        jan = AutentiqueSigner(
            public_id="1",
            name="Assinador",
            email="assinador@b4a.com.br",
            short_link=None,
            signed_at=None,
        )
        luciano = AutentiqueSigner(
            public_id="2",
            name="Beauty For All",
            email="juridico@b4a.com.br",
            short_link=None,
            signed_at=None,
        )

        assert signer_is_jan(luciano) is False
        assert signer_is_luciano(jan) is False

    def test_should_prefer_jan_when_name_is_jan_not_luciano(self) -> None:
        signer = AutentiqueSigner(
            public_id="1",
            name="Jan",
            email="jan@external.com",
            short_link=None,
            signed_at=None,
        )
        assert signer_is_jan(signer) is True
        assert signer_is_luciano(signer) is False
