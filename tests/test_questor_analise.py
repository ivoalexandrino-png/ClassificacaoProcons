"""Testes do núcleo de análise do Questor (regras de pendência)."""

from datetime import date, datetime

from classificacao_procons.questor.analise import (
    analyze_certidao,
    analyze_mensagem,
    analyze_snapshot,
)
from classificacao_procons.questor.models import (
    Certidao,
    MensagemCaixaPostal,
    QuestorSnapshot,
)

TODAY = date(2026, 8, 8)


def _certidao(**kwargs) -> Certidao:
    base = {"orgao": "Receita Federal / PGFN", "situacao": "negativa"}
    base.update(kwargs)
    return Certidao(**base)


class TestAnalyzeCertidao:
    def test_should_flag_positiva_as_critical(self) -> None:
        issues = analyze_certidao(_certidao(situacao="positiva"), today=TODAY)
        assert len(issues) == 1
        assert issues[0].kind == "certidao_positiva"
        assert issues[0].severity == "critical"

    def test_should_flag_vencida_by_status(self) -> None:
        issues = analyze_certidao(_certidao(situacao="vencida"), today=TODAY)
        assert issues[0].kind == "certidao_vencida"
        assert issues[0].severity == "critical"

    def test_should_flag_vencida_when_validade_in_past(self) -> None:
        certidao = _certidao(situacao="negativa", data_validade=date(2026, 8, 7))
        issues = analyze_certidao(certidao, today=TODAY)
        assert issues[0].kind == "certidao_vencida"

    def test_should_flag_indisponivel_as_warning(self) -> None:
        issues = analyze_certidao(_certidao(situacao="indisponivel"), today=TODAY)
        assert issues[0].kind == "certidao_indisponivel"
        assert issues[0].severity == "warning"

    def test_should_flag_restricao_as_critical(self) -> None:
        issues = analyze_certidao(_certidao(situacao="restricao"), today=TODAY)
        assert issues[0].kind == "certidao_restricao"
        assert issues[0].severity == "critical"

    def test_should_ignore_neutra(self) -> None:
        assert analyze_certidao(_certidao(situacao="neutra"), today=TODAY) == []

    def test_should_include_empresa_in_title_and_dedup(self) -> None:
        cert = _certidao(situacao="positiva", empresa="B4A")
        issue = analyze_certidao(cert, today=TODAY)[0]
        assert "B4A" in issue.title
        assert "b4a" in issue.dedup_key

    def test_should_warn_when_expiring_within_window(self) -> None:
        certidao = _certidao(data_validade=date(2026, 8, 20))
        issues = analyze_certidao(certidao, today=TODAY, warn_within_days=15)
        assert issues[0].kind == "certidao_a_vencer"
        assert issues[0].severity == "warning"

    def test_should_warn_on_exact_window_boundary(self) -> None:
        certidao = _certidao(data_validade=date(2026, 8, 23))
        issues = analyze_certidao(certidao, today=TODAY, warn_within_days=15)
        assert issues and issues[0].kind == "certidao_a_vencer"

    def test_should_not_warn_when_beyond_window(self) -> None:
        certidao = _certidao(data_validade=date(2026, 8, 24))
        assert analyze_certidao(certidao, today=TODAY, warn_within_days=15) == []

    def test_should_return_no_issue_for_valid_negativa(self) -> None:
        certidao = _certidao(data_validade=date(2026, 12, 31))
        assert analyze_certidao(certidao, today=TODAY) == []

    def test_should_treat_positiva_com_efeitos_as_regular(self) -> None:
        certidao = _certidao(
            situacao="positiva_com_efeitos_negativa",
            data_validade=date(2026, 12, 31),
        )
        assert analyze_certidao(certidao, today=TODAY) == []


class TestAnalyzeMensagem:
    def test_should_warn_on_unread_message(self) -> None:
        mensagem = MensagemCaixaPostal(orgao="e-CAC", assunto="Comunicado", lida=False)
        issues = analyze_mensagem(mensagem, today=TODAY)
        assert any(issue.kind == "mensagem_nao_lida" for issue in issues)

    def test_should_not_warn_on_read_message_without_deadline(self) -> None:
        mensagem = MensagemCaixaPostal(orgao="e-CAC", assunto="Comunicado", lida=True)
        assert analyze_mensagem(mensagem, today=TODAY) == []

    def test_should_flag_expired_ciencia_deadline_as_critical(self) -> None:
        mensagem = MensagemCaixaPostal(
            orgao="e-CAC",
            assunto="Intimação",
            lida=True,
            prazo_ciencia=date(2026, 8, 1),
        )
        issues = analyze_mensagem(mensagem, today=TODAY)
        assert issues[0].kind == "prazo_ciencia_vencido"
        assert issues[0].severity == "critical"

    def test_should_flag_upcoming_ciencia_deadline_as_critical(self) -> None:
        mensagem = MensagemCaixaPostal(
            orgao="e-CAC",
            assunto="Intimação",
            lida=True,
            prazo_ciencia=date(2026, 8, 15),
        )
        issues = analyze_mensagem(mensagem, today=TODAY, warn_within_days=15)
        assert issues[0].kind == "prazo_ciencia_proximo"

    def test_should_not_duplicate_unread_when_deadline_present(self) -> None:
        mensagem = MensagemCaixaPostal(
            orgao="e-CAC",
            assunto="Intimação",
            lida=False,
            prazo_ciencia=date(2026, 8, 1),
        )
        kinds = [issue.kind for issue in analyze_mensagem(mensagem, today=TODAY)]
        assert kinds == ["prazo_ciencia_vencido"]


class TestAnalyzeSnapshot:
    def test_should_aggregate_and_sort_by_severity(self) -> None:
        snapshot = QuestorSnapshot(
            captured_at=datetime(2026, 8, 8, 9, 0),
            empresa="Beauty For All",
            cnpj="12345678000199",
            certidoes=(
                _certidao(data_validade=date(2026, 12, 31)),  # ok
                _certidao(orgao="FGTS/CRF", situacao="positiva"),  # crítico
                _certidao(orgao="Municipal", data_validade=date(2026, 8, 18)),  # aviso
            ),
            mensagens=(
                MensagemCaixaPostal(orgao="e-CAC", assunto="Aviso", lida=False),
            ),
        )
        analysis = analyze_snapshot(snapshot, today=TODAY)
        assert analysis.has_problems
        assert len(analysis.issues) == 3
        assert analysis.issues[0].severity == "critical"
        assert len(analysis.critical_issues) == 1

    def test_should_report_no_problems_when_all_regular(self) -> None:
        snapshot = QuestorSnapshot(
            captured_at=datetime(2026, 8, 8, 9, 0),
            certidoes=(_certidao(data_validade=date(2026, 12, 31)),),
            mensagens=(MensagemCaixaPostal(orgao="e-CAC", assunto="Ok", lida=True),),
        )
        analysis = analyze_snapshot(snapshot, today=TODAY)
        assert not analysis.has_problems
        assert analysis.issues == ()
