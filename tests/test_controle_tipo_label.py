"""Testes de Tipo no Controle para documentos sem automação Contratos."""

from classificacao_procons.contratos.controle_sync import _resolve_tipo_label


class TestResolveControleTipoLabel:
    def test_should_return_none_for_procuracao(self) -> None:
        assert (
            _resolve_tipo_label(
                document_name="Procuração - Jan __ Carol - localiza 16.07.2026",
            )
            is None
        )

    def test_should_keep_b2b_for_parceria_minuta(self) -> None:
        assert (
            _resolve_tipo_label(
                document_name="4.1 - Minuta Contrato Parceria - B4A - GE Beauty",
            )
            == "Contratos B2B"
        )
