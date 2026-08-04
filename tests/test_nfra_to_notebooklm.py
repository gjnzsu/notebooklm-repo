import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pypdf import PdfReader

from scripts.nfra_to_notebooklm import (
    build_upload_commands,
    extract_document,
    is_synced,
    make_pdf_filename,
    parse_source_id,
    resolve_notebook_id,
    run_sync,
    select_documents,
    write_pdf,
)


class FilenameTests(unittest.TestCase):
    def test_uses_first_ten_characters_and_removes_windows_invalid_characters(self):
        filename = make_pdf_filename(
            "2026-07-07",
            'NFRA: issues the "Rules"',
            1264482,
            existing_names=set(),
        )

        self.assertEqual(filename, "20260707-NFRA issue.pdf")

    def test_appends_document_id_only_when_truncated_name_collides(self):
        filename = make_pdf_filename(
            "2026-07-07",
            "NFRA issues another rule",
            999,
            existing_names={"20260707-NFRA issue.pdf"},
        )

        self.assertEqual(filename, "20260707-NFRA issue-999.pdf")


class SelectionTests(unittest.TestCase):
    def test_selects_all_documents_published_on_target_date(self):
        rows = [
            {"docId": 1, "docTitle": "Today", "publishDate": "2026-07-07 15:41:00"},
            {"docId": 2, "docTitle": "Earlier", "publishDate": "2026-07-06 23:59:59"},
        ]

        selected = select_documents(rows, "2026-07-07")

        self.assertEqual([item["docId"] for item in selected], [1])


class ExtractionTests(unittest.TestCase):
    def test_extracts_readable_paragraphs_and_links_from_nfra_html(self):
        payload = {
            "docTitle": "A new rule",
            "publishDate": "2026-07-07 15:41:00",
            "docClob": "<p>First paragraph.</p><p>Read <a href='/file.pdf'>the attachment</a>.</p>",
        }

        document = extract_document(payload, 123)

        self.assertEqual(document["title"], "A new rule")
        self.assertEqual(document["paragraphs"], ["First paragraph.", "Read the attachment."])
        self.assertEqual(document["links"], [("the attachment", "https://www.nfra.gov.cn/file.pdf")])

    def test_normalizes_smart_punctuation_for_reliable_pdf_text(self):
        payload = {
            "docTitle": "Rule",
            "publishDate": "2026-07-07",
            "docClob": "<p>China<span>’</span><span>s</span> market<span>—</span>safe and sound.</p>",
        }

        document = extract_document(payload, 123)

        self.assertEqual(document["paragraphs"], ["China's market-safe and sound."])

    def test_rejects_empty_document_body(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            extract_document({"docTitle": "Empty", "publishDate": "2026-07-07", "docClob": "<p>&nbsp;</p>"}, 123)


class NotebookTests(unittest.TestCase):
    def test_resolves_exact_notebook_title(self):
        notebooks = {
            "notebooks": [
                {"id": "wrong", "title": "NFRA Archive"},
                {"id": "right", "title": "NFRA"},
            ]
        }

        self.assertEqual(resolve_notebook_id(notebooks, "NFRA"), "right")

    def test_builds_file_upload_and_wait_commands(self):
        add, wait = build_upload_commands(Path("C:/out/rule.pdf"), "book-id", "Rule title", "source-id")

        self.assertEqual(
            add,
            ["notebooklm", "source", "add", "--json", "--notebook", "book-id", "--type", "file", "--title", "Rule title", "C:\\out\\rule.pdf"],
        )
        self.assertEqual(wait, ["notebooklm", "source", "wait", "source-id", "--notebook", "book-id", "--timeout", "180", "--interval", "2", "--json"])

    def test_parses_source_id_from_cli_response(self):
        self.assertEqual(parse_source_id({"source": {"id": "source-id"}}), "source-id")


class StateTests(unittest.TestCase):
    def test_only_successfully_uploaded_document_is_synced(self):
        state = {"documents": {"123": {"status": "uploaded"}, "456": {"status": "generated"}}}

        self.assertTrue(is_synced(state, 123))
        self.assertFalse(is_synced(state, 456))


class PdfTests(unittest.TestCase):
    def test_writes_pdf_with_title_metadata_and_body(self):
        document = {
            "doc_id": 123,
            "title": "A new NFRA rule",
            "publish_date": "2026-07-07",
            "source_url": "https://www.nfra.gov.cn/example",
            "paragraphs": ["First paragraph.", "Second paragraph."],
            "links": [],
        }
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "rule.pdf"

            write_pdf(document, path)

            text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
            self.assertIn("A new NFRA rule", text)
            self.assertIn("Publication date: 2026-07-07", text)
            self.assertIn("First paragraph.", text)


class SyncTests(unittest.TestCase):
    def test_no_matching_documents_is_successful_noop_without_notebook_commands(self):
        calls = []

        def fake_get(url, params):
            return {"rptCode": 200, "data": {"rows": [{"docId": 1, "publishDate": "2026-07-06 12:00:00"}]}}

        def forbidden_command(args):
            calls.append(args)
            raise AssertionError("NotebookLM must not be called for a no-op run")

        with TemporaryDirectory() as temp_dir:
            result = run_sync(
                target_date="2026-07-07",
                output_dir=Path(temp_dir) / "pdf",
                state_path=Path(temp_dir) / "state.json",
                upload=True,
                http_get_json=fake_get,
                command_runner=forbidden_command,
            )

        self.assertEqual(result["counts"], {"matched": 0, "generated": 0, "uploaded": 0, "skipped": 0, "failed": 0})
        self.assertEqual(calls, [])


class PowerShellRegistrationTests(unittest.TestCase):
    def test_scheduled_task_is_allowed_to_start_and_continue_on_battery(self):
        script = Path("scripts/Register-NfraNotebookLmSyncTask.ps1").read_text(encoding="utf-8")

        self.assertIn("-AllowStartIfOnBatteries", script)
        self.assertIn("-DontStopIfGoingOnBatteries", script)


if __name__ == "__main__":
    unittest.main()
