"""Testes do parser de intimações judiciais."""

from datetime import date, datetime

import pytest

from classificacao_procons.juridico.models import (
    NOTIFICATION_TYPE_AUDIENCIA,
    NOTIFICATION_TYPE_CITACAO,
    NOTIFICATION_TYPE_DECISAO,
    NOTIFICATION_TYPE_INTIMACAO,
    NOTIFICATION_TYPE_SENTENCA,
)
from classificacao_procons.juridico.parser import (
    IntimacaoParseError,
    is_judicial_notification,
    parse_judicial_notification_body,
    parse_judicial_notifications,
)

# Estrutura real de recorte de publicações (OAB/Jusbrasil): um e-mail com
# publicações de processos diferentes, cada um com seu tipo e seu prazo.
RECORTE_MULTIPROCESSO_TEXT = """
Recorte Digital OAB/SP. Public. 2. DJSP 21/07/26

Processo 1013709-36.2020.8.26.0309 - Apelação Cível - Marca - || Despacho:
apresente a apelante contrarrazões ao recurso adesivo, bem como para juntar
documentos que ilidam as afirmações da demandada. Prazo: dez dias.
- Magistrado(a) Ricardo Negrão - 2ª Câmara Reservada de Direito Empresarial.

Processo 1000817-79.2026.5.02.0511 - Ação Trabalhista - Rito Sumaríssimo -
Despacho Vistos... ID 8f6a596: intimem-se as partes quanto ao laudo pericial.
Prazo: 15 dias para manifestação. Itapevi/SP, 20 de julho de 2026.
Tabajara Medeiros de Rezende Filho Juiz do Trabalho Titular
Intimado(s)/Citado(s) - B4A COMERCIO DE COSMETICOS E SERVICOS S.A.
"""

PJE_INTIMACAO_TEXT = """
Poder Judiciário do Estado de São Paulo
1ª Vara Cível do Foro Central da Comarca de São Paulo

Processo nº 1001234-56.2026.8.26.0100
Classe: Procedimento Comum Cível

Fica a parte ré INTIMADA da decisão proferida nos autos, devendo apresentar
manifestação no prazo de 15 (quinze) dias úteis.
"""

CITACAO_TEXT = """
JUSTIÇA DO TRABALHO — 2ª Vara do Trabalho de São Paulo
Processo 0001234-56.2026.5.02.0011

CITAÇÃO da empresa ré para apresentar defesa no prazo de 15 dias.
"""

AUDIENCIA_HTML = """
<html><body>
<p>Processo nº 1001234-56.2026.8.26.0100</p>
<p>Audiência de conciliação designada para o dia 05/08/2026 às 14:30,
na 3ª Vara Cível de São Paulo.</p>
</body></html>
"""


class TestIsJudicialNotification:
    def test_should_match_when_sender_is_jus_br(self) -> None:
        assert is_judicial_notification(
            subject="Qualquer assunto",
            sender="PJe TJSP <naoresponda@tjsp.jus.br>",
        )

    def test_should_match_domicilio_judicial_eletronico(self) -> None:
        assert is_judicial_notification(
            subject="Domicílio Judicial Eletrônico — nova comunicação processual",
            sender="nao-responda@comunica.pje.jus.br",
        )

    def test_should_match_when_subject_has_push_keyword(self) -> None:
        assert is_judicial_notification(
            subject="Push: nova movimentação processual",
            sender="alertas@servicopush.com.br",
        )

    def test_should_match_when_subject_has_intimacao_with_accents(self) -> None:
        assert is_judicial_notification(
            subject="Intimação eletrônica — processo em andamento",
            sender="alguem@example.com",
        )

    def test_should_match_forwarded_email_with_fwd_prefix(self) -> None:
        assert is_judicial_notification(
            subject="Fwd: Intimação eletrônica",
            sender="advogado.pessoal@gmail.com",
        )

    def test_should_match_forwarded_email_with_jus_br_in_body(self) -> None:
        body = (
            "---------- Forwarded message ----------\n"
            "De: PJe TJSP <naoresponda@tjsp.jus.br>\n"
            "Assunto: Expediente\n\n"
            "Processo 1001234-56.2026.8.26.0100."
        )
        assert is_judicial_notification(
            subject="Olha isso aqui",
            sender="advogado.pessoal@gmail.com",
            body=body,
        )

    def test_should_match_default_forwarder_without_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("JURIDICO_FORWARDER_EMAILS", raising=False)
        assert is_judicial_notification(
            subject="Segue para providências",
            sender="Ivo <adv.ialexandrino@gmail.com>",
            body="Processo 1001234-56.2026.8.26.0100 — prazo de 15 dias na 1ª Vara Cível.",
        )

    def test_should_match_dje_official_sender(self) -> None:
        assert is_judicial_notification(
            subject="Nova comunicação",
            sender="domicilio.comunicacoes@cnj.jus.br",
        )

    def test_should_match_forwarder_email_with_judicial_body(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(
            "JURIDICO_FORWARDER_EMAILS",
            "advogado.pessoal@gmail.com, outro@gmail.com",
        )
        assert is_judicial_notification(
            subject="Segue para providências",
            sender="Advogado <advogado.pessoal@gmail.com>",
            body="Processo 1001234-56.2026.8.26.0100 — prazo de 15 dias na 1ª Vara Cível.",
        )

    def test_should_not_match_forwarder_email_without_judicial_content(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("JURIDICO_FORWARDER_EMAILS", "advogado.pessoal@gmail.com")
        assert not is_judicial_notification(
            subject="Almoço amanhã?",
            sender="advogado.pessoal@gmail.com",
            body="Confirma o horário do restaurante.",
        )

    def test_should_match_any_sender_when_body_has_cnj_and_judicial_terms(self) -> None:
        assert is_judicial_notification(
            subject="Encaminhando",
            sender="alguem@example.com",
            body="Intimação no processo 1001234-56.2026.8.26.0100, prazo de 5 dias.",
        )

    def test_should_not_match_when_sender_and_subject_are_unrelated(self) -> None:
        assert not is_judicial_notification(
            subject="Promoção imperdível",
            sender="marketing@loja.com.br",
        )

    def test_should_not_match_marketing_email_with_body(self) -> None:
        assert not is_judicial_notification(
            subject="Promoção imperdível",
            sender="marketing@loja.com.br",
            body="Aproveite 50% de desconto em toda a loja!",
        )


class TestParseJudicialNotificationBody:
    def test_should_parse_intimacao_with_deadline_in_business_days(self) -> None:
        result = parse_judicial_notification_body(text=PJE_INTIMACAO_TEXT)

        assert result.process_number == "1001234-56.2026.8.26.0100"
        assert result.notification_type == NOTIFICATION_TYPE_DECISAO
        assert result.tribunal == "TJSP"
        assert result.court_unit is not None
        assert "Vara Civel do Foro Central" in result.court_unit
        assert result.deadline_days == 15
        assert result.deadline_in_business_days is True
        assert result.hearing_datetime is None

    def test_should_parse_citacao_from_labor_court(self) -> None:
        result = parse_judicial_notification_body(text=CITACAO_TEXT)

        assert result.process_number == "0001234-56.2026.5.02.0011"
        assert result.notification_type == NOTIFICATION_TYPE_CITACAO
        assert result.tribunal == "TRT2"
        assert result.deadline_days == 15

    def test_should_parse_hearing_date_and_time_from_html(self) -> None:
        result = parse_judicial_notification_body(html=AUDIENCIA_HTML)

        assert result.notification_type == NOTIFICATION_TYPE_AUDIENCIA
        assert result.hearing_datetime == datetime(2026, 8, 5, 14, 30)

    def test_should_parse_explicit_deadline_date(self) -> None:
        text = (
            "Processo 1001234-56.2026.8.26.0100. Intimação: prazo fatal em 20/08/2026 "
            "para manifestação."
        )
        result = parse_judicial_notification_body(text=text)
        assert result.deadline_date == date(2026, 8, 20)

    def test_should_flag_calendar_days_when_prazo_corrido(self) -> None:
        text = "Processo 1001234-56.2026.8.26.0100. Prazo de 10 dias corridos."
        result = parse_judicial_notification_body(text=text)
        assert result.deadline_days == 10
        assert result.deadline_in_business_days is False

    def test_should_detect_sentenca(self) -> None:
        text = "Processo 1001234-56.2026.8.26.0100. Publicada a sentença nos autos."
        result = parse_judicial_notification_body(text=text)
        assert result.notification_type == NOTIFICATION_TYPE_SENTENCA

    def test_should_default_to_intimacao_when_type_is_unclear(self) -> None:
        text = "Processo 1001234-56.2026.8.26.0100. Juntada de petição."
        result = parse_judicial_notification_body(text=text)
        assert result.notification_type == NOTIFICATION_TYPE_INTIMACAO

    def test_should_detect_citacao_with_cite_se(self) -> None:
        text = "Processo 1001234-56.2026.8.26.0100. Cite-se a parte ré."
        result = parse_judicial_notification_body(text=text)
        assert result.notification_type == NOTIFICATION_TYPE_CITACAO

    def test_should_detect_citacao_when_citado_para_contestar(self) -> None:
        text = (
            "Processo 1001234-56.2026.8.26.0100. O réu fica citado para "
            "apresentar contestação no prazo legal."
        )
        result = parse_judicial_notification_body(text=text)
        assert result.notification_type == NOTIFICATION_TYPE_CITACAO

    def test_should_not_detect_citacao_from_recurso_acima_citado(self) -> None:
        """Falso positivo real (PROJUDI): "recurso acima citado" não é citação."""
        text = (
            "Processo 0026891-32.2026.8.16.0000. Uma intimação no recurso acima "
            "citado, referente à movimentação Juntada de Acórdão, foi expedida."
        )
        result = parse_judicial_notification_body(text=text)
        assert result.notification_type == NOTIFICATION_TYPE_INTIMACAO

    def test_should_not_detect_citacao_from_intimado_citado_party_list(self) -> None:
        """Falso positivo real (Recorte OAB): lista "Intimado(s)/Citado(s) - …"."""
        text = (
            "Processo 1013709-36.2020.8.26.0309. Despacho nos autos. "
            "Intimado(s)/Citado(s) - B4A Comercio de Cosmeticos e Servicos S.A."
        )
        result = parse_judicial_notification_body(text=text)
        assert result.notification_type == NOTIFICATION_TYPE_DECISAO

    def test_should_not_detect_citacao_from_projudi_subject_boilerplate(self) -> None:
        text = "Processo 1001234-56.2026.8.26.0100. [PROJUDI] Informação de intimação/citação."
        result = parse_judicial_notification_body(text=text)
        assert result.notification_type == NOTIFICATION_TYPE_INTIMACAO

    def test_should_flag_deadline_trigger_when_intimacao_published_pje(self) -> None:
        """Push real do TRT2/PJe: intimação publicada sem prazo no texto."""
        text = (
            "Processo 1001205-83.2025.5.02.0036. Eventos:\n"
            "18/07/2026 02:11 Publicado(a) o(a) intimação em 17/07/2026\n"
            "18/07/2026 02:11 Disponibilizado(a) o(a) intimação no Diário da Justiça"
        )
        result = parse_judicial_notification_body(text=text)
        assert result.has_deadline_trigger is True
        assert result.deadline_days is None

    def test_should_flag_deadline_trigger_on_eproc_carta_entregue(self) -> None:
        """Push real do eproc TJSC: carta com comprovante de entrega."""
        text = (
            "Num. Processo: 5007602-83.2026.8.24.0039\n"
            "Movimentação: Juntada de carta pelo correio - comprovante de entrega -"
        )
        result = parse_judicial_notification_body(text=text)
        assert result.has_deadline_trigger is True

    def test_should_flag_deadline_trigger_on_jusbrasil_publication(self) -> None:
        text = (
            "Processo 5052249-56.2022.8.24.0023. Ivo, os processos que você acompanha "
            "possuem novas informações! 1 nova publicação encontrada para você."
        )
        result = parse_judicial_notification_body(text=text)
        assert result.has_deadline_trigger is True

    def test_should_extract_deadline_written_in_words(self) -> None:
        """Publicação real: "prazo: dez dias" (por extenso)."""
        text = (
            "Processo 1013709-36.2020.8.26.0309. Apresente contrarrazões, bem como "
            "junte documentos. Prazo: dez dias."
        )
        result = parse_judicial_notification_body(text=text)
        assert result.deadline_days == 10
        assert result.deadline_in_business_days is True

    def test_should_extract_deadline_in_words_with_corridos(self) -> None:
        text = "Processo 1001234-56.2026.8.26.0100. Prazo de quinze dias corridos."
        result = parse_judicial_notification_body(text=text)
        assert result.deadline_days == 15
        assert result.deadline_in_business_days is False

    def test_should_not_flag_trigger_on_decorrido_prazo_or_sigiloso(self) -> None:
        for text in (
            "Num. Processo: 4033019-49.2025.8.26.0002. Movimentação: Decorrido prazo -",
            "Processo 1000817-79.2026.5.02.0511. Eventos: 19/07/2026 documento sigiloso",
        ):
            result = parse_judicial_notification_body(text=text)
            assert result.has_deadline_trigger is False, text

    def test_should_use_subject_when_body_lacks_process_number(self) -> None:
        result = parse_judicial_notification_body(
            text="Nova movimentação disponível no sistema.",
            subject="Push processo 1001234-56.2026.8.26.0100",
        )
        assert result.process_number == "1001234-56.2026.8.26.0100"

    def test_should_raise_when_body_is_empty(self) -> None:
        with pytest.raises(IntimacaoParseError, match="Corpo do e-mail vazio"):
            parse_judicial_notification_body()

    def test_should_raise_when_process_number_is_missing(self) -> None:
        with pytest.raises(IntimacaoParseError, match="Número de processo"):
            parse_judicial_notification_body(text="Intimação sem número nenhum.")

    def test_should_split_recorte_into_one_intimacao_per_process(self) -> None:
        """Recorte com 2 processos: cada um com seu prazo e sua triagem."""
        results = parse_judicial_notifications(
            text=RECORTE_MULTIPROCESSO_TEXT,
            subject="Fwd: Recorte Digital OAB/SP. Public. 2. DJSP 21/07/26",
        )

        assert len(results) == 2
        by_process = {item.process_number: item for item in results}

        tjsp = by_process["1013709-36.2020.8.26.0309"]
        assert tjsp.deadline_days == 10  # "prazo: dez dias" por extenso
        assert tjsp.tribunal == "TJSP"

        trt = by_process["1000817-79.2026.5.02.0511"]
        assert trt.deadline_days == 15  # prazo do laudo pericial, não o do TJSP
        assert trt.tribunal == "TRT2"
        assert "laudo pericial" in trt.summary

    def test_should_keep_single_process_email_as_one_intimacao(self) -> None:
        results = parse_judicial_notifications(text=CITACAO_TEXT)
        assert len(results) == 1
        assert results[0].process_number == "0001234-56.2026.5.02.0011"

    def test_should_merge_repeated_segments_of_same_process(self) -> None:
        """eproc lista o mesmo processo várias vezes (um bloco por evento)."""
        text = (
            "Num. Processo: 5007602-83.2026.8.24.0039\n"
            "Movimentação: Juntada de carta pelo correio - comprovante de entrega -\n\n"
            "Num. Processo: 5007602-83.2026.8.24.0039\n"
            "Movimentação: Decorrido prazo -\n"
        )
        results = parse_judicial_notifications(text=text)
        assert len(results) == 1
        assert results[0].process_number == "5007602-83.2026.8.24.0039"
        assert results[0].has_deadline_trigger is True

    def test_should_truncate_long_summary(self) -> None:
        text = "Processo 1001234-56.2026.8.26.0100. " + "conteúdo " * 200
        result = parse_judicial_notification_body(text=text)
        assert len(result.summary) <= 600
