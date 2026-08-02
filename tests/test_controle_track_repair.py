"""Testes de reparo das filas Jan/Luciano no Controle."""

from classificacao_procons.contratos.controle_track_repair import classify_controle_item_track
from classificacao_procons.contratos.models import ControleAssinaturasItem


class TestClassifyControleItemTrack:
    def test_should_classify_item_with_tipo_as_jan_even_in_luciano_group(self) -> None:
        item = ControleAssinaturasItem(
            item_id="1",
            name="4.1 - Minuta Contrato Parceria - B4A - GE Beauty",
            status="Aguardando Assinatura",
            tipo="Contratos B2B",
            signature_link="Autentique ID: abc",
            group_id="g-luciano",
        )

        track = classify_controle_item_track(
            item,
            jan_group_id="g-jan",
            luciano_group_id="g-luciano",
        )

        assert track == "jan"

    def test_should_classify_item_without_tipo_in_luciano_group_as_luciano(self) -> None:
        item = ControleAssinaturasItem(
            item_id="2",
            name="4.1 - Minuta Contrato Parceria - B4A - GE Beauty",
            status="Aguardando Assinatura",
            tipo=None,
            signature_link="Autentique ID: abc",
            group_id="g-luciano",
        )

        track = classify_controle_item_track(
            item,
            jan_group_id="g-jan",
            luciano_group_id="g-luciano",
        )

        assert track == "luciano"
