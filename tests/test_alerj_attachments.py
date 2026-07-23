"""Testes de anexos ALERJ."""

from classificacao_procons.alerj.attachments import find_alerj_pdf_attachment


class TestAlerjAttachments:
    def test_should_find_not_pdf_attachment(self) -> None:
        payload = {
            "parts": [
                {
                    "filename": "Outlook-logo.png",
                    "body": {"attachmentId": "img-1", "size": 100},
                },
                {
                    "filename": "312133NOT.pdf",
                    "body": {"attachmentId": "pdf-1", "size": 367208},
                },
            ],
        }
        attachment = find_alerj_pdf_attachment(payload)
        assert attachment is not None
        assert attachment.filename == "312133NOT.pdf"
        assert attachment.attachment_id == "pdf-1"

    def test_should_return_none_when_pdf_missing(self) -> None:
        payload = {"parts": [{"filename": "outro.pdf", "body": {"attachmentId": "x", "size": 1}}]}
        assert find_alerj_pdf_attachment(payload) is None
