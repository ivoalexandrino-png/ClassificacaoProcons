"""Testes de leitura de pasta SAC no Drive."""

from unittest.mock import MagicMock, patch

from classificacao_procons.drive.reader import (
    DriveFileInfo,
    _build_sac_context_from_folder_children,
)


class TestSacFolderReader:
    def test_should_build_context_from_flat_legacy_folder(self) -> None:
        children = [
            DriveFileInfo(
                "pdf-1",
                "Atendimento Procon - MARIA - 123-2026.pdf",
                "application/pdf",
                None,
            ),
            DriveFileInfo("txt-1", "informacoes-sac.txt", "text/plain", None),
            DriveFileInfo("img-1", "comprovante.png", "image/png", None),
        ]

        context = _build_sac_context_from_folder_children(
            consumer_folder_id="folder-root",
            children=children,
        )

        assert context is not None
        assert context.consumer_folder_id == "folder-root"
        assert context.sac_folder_id == "folder-root"
        assert context.complaint_pdf.file_id == "pdf-1"
        assert context.summary_txt is not None
        assert context.summary_txt.file_id == "txt-1"
        assert len(context.supporting_files) == 1

    def test_should_return_none_when_flat_folder_missing_txt(self) -> None:
        children = [
            DriveFileInfo("pdf-1", "reclamacao.pdf", "application/pdf", None),
        ]

        assert (
            _build_sac_context_from_folder_children(
                consumer_folder_id="folder-root",
                children=children,
            )
            is None
        )

    @patch("classificacao_procons.drive.reader._list_children")
    @patch("classificacao_procons.drive.reader._get_file_metadata")
    @patch("classificacao_procons.drive.reader._build_drive_service")
    def test_should_resolve_flat_folder_from_docs_sac_link(
        self,
        build_service_mock,
        metadata_mock,
        list_children_mock,
    ) -> None:
        from classificacao_procons.drive.reader import resolve_sac_folder_context

        build_service_mock.return_value = MagicMock()
        metadata_mock.return_value = DriveFileInfo(
            "folder-root",
            "MARIA SILVA",
            "application/vnd.google-apps.folder",
            None,
        )
        list_children_mock.return_value = [
            DriveFileInfo("pdf-1", "Atendimento Procon - MARIA.pdf", "application/pdf", None),
            DriveFileInfo("txt-1", "resumo-sac.txt", "text/plain", None),
        ]

        context = resolve_sac_folder_context(
            docs_sac_url="https://drive.google.com/drive/folders/folder-root",
        )

        assert context.consumer_folder_id == "folder-root"
        assert context.summary_txt is not None

    @patch("classificacao_procons.drive.reader._list_children")
    @patch("classificacao_procons.drive.reader._get_file_metadata")
    @patch("classificacao_procons.drive.reader._get_parent_folder_id")
    @patch("classificacao_procons.drive.reader._build_drive_service")
    def test_should_use_notificacao_pdf_when_missing_in_sac_folder(
        self,
        build_service_mock,
        parent_mock,
        metadata_mock,
        list_children_mock,
    ) -> None:
        from classificacao_procons.drive.reader import resolve_sac_folder_context

        build_service_mock.return_value = MagicMock()
        parent_mock.return_value = None
        metadata_mock.side_effect = [
            DriveFileInfo(
                "folder-root",
                "ANTIGA",
                "application/vnd.google-apps.folder",
                None,
            ),
            DriveFileInfo(
                "pdf-ext",
                "Atendimento Procon - ANTIGA.pdf",
                "application/pdf",
                None,
                web_view_link="https://drive.google.com/file/d/pdf-ext/view",
            ),
        ]

        def list_children_side_effect(service, *, folder_id: str) -> list[DriveFileInfo]:
            if folder_id == "folder-root":
                return [
                    DriveFileInfo(
                        "sac-folder",
                        "Informações SAC",
                        "application/vnd.google-apps.folder",
                        None,
                    ),
                ]
            if folder_id == "sac-folder":
                return [
                    DriveFileInfo("txt-1", "informacoes-sac.txt", "text/plain", None),
                ]
            return []

        list_children_mock.side_effect = list_children_side_effect

        context = resolve_sac_folder_context(
            docs_sac_url="https://drive.google.com/drive/folders/folder-root",
            complaint_pdf_url="https://drive.google.com/file/d/pdf-ext/view",
        )

        assert context.complaint_pdf.file_id == "pdf-ext"
        assert context.summary_txt is not None
        assert context.summary_txt.file_id == "txt-1"
