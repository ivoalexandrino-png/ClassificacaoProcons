"""Testes do registro de fontes de fomento."""

from classificacao_procons.radar.sources import (
    all_sources,
    get_sources,
    source_by_key,
)


class TestSourcesRegistry:
    def test_should_have_national_and_international_sources(self) -> None:
        scopes = {source.scope for source in all_sources()}
        assert scopes == {"nacional", "internacional"}

    def test_should_lookup_by_key(self) -> None:
        assert source_by_key("cnpq") is not None
        assert source_by_key("inexistente") is None

    def test_should_filter_by_scope(self) -> None:
        internacionais = get_sources(scope="internacional")
        assert internacionais
        assert all(source.scope == "internacional" for source in internacionais)

    def test_should_filter_by_area_including_multidisciplinar(self) -> None:
        saude = get_sources(area="saude")
        keys = {source.key for source in saude}
        # Fonte temática de saúde e fonte multidisciplinar devem aparecer.
        assert "nih" in keys
        assert "cnpq" in keys

    def test_should_filter_by_keys(self) -> None:
        selected = get_sources(keys=("cnpq", "nih"))
        assert {source.key for source in selected} == {"cnpq", "nih"}

    def test_all_sources_have_unique_keys(self) -> None:
        keys = [source.key for source in all_sources()]
        assert len(keys) == len(set(keys))
