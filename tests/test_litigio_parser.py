"""Testes da heurística de classificação de providências."""

from datetime import date

from classificacao_procons.litigio.models import Intimacao, ProvidenciaTipo
from classificacao_procons.litigio.parser import analisar_intimacao, analisar_texto_bruto


def _intimacao(**overrides: object) -> Intimacao:
    defaults: dict[str, object] = {
        "id": 1,
        "hash": "hash-1",
        "numero_processo": "00000012320268260100",
        "numero_processo_formatado": "0000001-23.2026.8.26.0100",
        "tribunal": "TJSP",
        "tipo_comunicacao": "Intimação",
        "tipo_documento": "Despacho",
        "orgao": "1ª Vara Cível",
        "classe_processual": "Procedimento Comum",
        "data_disponibilizacao": date(2026, 7, 11),
        "texto": "",
    }
    defaults.update(overrides)
    return Intimacao(**defaults)  # type: ignore[arg-type]


class TestAnalisarIntimacaoManifestacao:
    def test_should_extract_prazo_and_classify_manifestacao(self) -> None:
        intimacao = _intimacao(
            texto=(
                "Vistos. Intime-se a parte requerida para, no prazo de 15 (quinze) dias, "
                "apresentar manifestação sobre os documentos juntados."
            ),
        )
        providencia = analisar_intimacao(intimacao)

        assert providencia.tipo == ProvidenciaTipo.MANIFESTACAO
        assert providencia.requer_atencao is True
        assert providencia.prazo_dias == 15
        assert providencia.prazo_data == date(2026, 7, 26)
        assert providencia.data_audiencia is None

    def test_should_classify_manifestacao_when_only_prazo_is_found(self) -> None:
        intimacao = _intimacao(texto="Intime-se no prazo de 5 dias.")
        providencia = analisar_intimacao(intimacao)

        assert providencia.tipo == ProvidenciaTipo.MANIFESTACAO
        assert providencia.prazo_dias == 5


class TestAnalisarIntimacaoAudiencia:
    def test_should_extract_data_and_classify_audiencia(self) -> None:
        intimacao = _intimacao(
            texto=(
                "Fica a parte intimada de que foi designada AUDIÊNCIA de instrução "
                "para o dia 20/08/2026, às 14h."
            ),
        )
        providencia = analisar_intimacao(intimacao)

        assert providencia.tipo == ProvidenciaTipo.AUDIENCIA
        assert providencia.requer_atencao is True
        assert providencia.data_audiencia == date(2026, 8, 20)

    def test_should_prioritize_audiencia_over_prazo_when_both_present(self) -> None:
        intimacao = _intimacao(
            texto=(
                "AUDIÊNCIA designada para o dia 01/09/2026. Prazo de 10 dias para "
                "manifestação sobre provas."
            ),
        )
        providencia = analisar_intimacao(intimacao)

        assert providencia.tipo == ProvidenciaTipo.AUDIENCIA
        assert providencia.data_audiencia == date(2026, 9, 1)


class TestAnalisarIntimacaoRecursoEPagamento:
    def test_should_classify_recurso_when_keyword_present(self) -> None:
        intimacao = _intimacao(texto="Prazo de 15 dias para interpor recurso de apelação.")
        providencia = analisar_intimacao(intimacao)
        assert providencia.tipo == ProvidenciaTipo.RECURSO

    def test_should_classify_pagamento_deposito_when_keyword_present(self) -> None:
        intimacao = _intimacao(
            texto="Intime-se para efetuar o depósito judicial no prazo de 10 dias.",
        )
        providencia = analisar_intimacao(intimacao)
        assert providencia.tipo == ProvidenciaTipo.PAGAMENTO_DEPOSITO


class TestAnalisarIntimacaoCiencia:
    def test_should_classify_ciencia_and_not_require_attention_when_no_action_needed(
        self,
    ) -> None:
        intimacao = _intimacao(
            tipo_documento="Ato ordinatório",
            texto="Tomar ciência do despacho proferido nos autos.",
        )
        providencia = analisar_intimacao(intimacao)

        assert providencia.tipo == ProvidenciaTipo.CIENCIA
        assert providencia.requer_atencao is False
        assert providencia.prazo_dias is None

    def test_should_classify_ciencia_when_texto_is_empty(self) -> None:
        intimacao = _intimacao(tipo_documento="Certidão", texto="")
        providencia = analisar_intimacao(intimacao)

        assert providencia.tipo == ProvidenciaTipo.CIENCIA
        assert providencia.requer_atencao is False


class TestAnalisarIntimacaoIndefinida:
    def test_should_classify_indefinida_and_require_attention_when_unrecognized(self) -> None:
        intimacao = _intimacao(
            tipo_documento="Ofício",
            texto="Comunicamos que os autos foram remetidos à Contadoria Judicial.",
        )
        providencia = analisar_intimacao(intimacao)

        assert providencia.tipo == ProvidenciaTipo.INDEFINIDA
        assert providencia.requer_atencao is True


class TestAnalisarIntimacaoCancelada:
    def test_should_not_require_attention_when_intimacao_is_cancelled(self) -> None:
        intimacao = _intimacao(
            texto="Intime-se no prazo de 15 dias para manifestação.",
            motivo_cancelamento="Erro de expedição",
        )
        providencia = analisar_intimacao(intimacao)

        assert providencia.requer_atencao is False
        assert providencia.prazo_dias is None
        assert "cancelada" in providencia.descricao.lower()


class TestAnalisarTextoBruto:
    def test_should_analyze_raw_text_without_djen_data(self) -> None:
        providencia = analisar_texto_bruto(
            texto="Prazo de 20 dias para réplica à impugnação.",
            data_disponibilizacao=date(2026, 1, 1),
            numero_processo="123",
        )

        assert providencia.numero_processo == "123"
        assert providencia.tipo == ProvidenciaTipo.MANIFESTACAO
        assert providencia.prazo_data == date(2026, 1, 21)
