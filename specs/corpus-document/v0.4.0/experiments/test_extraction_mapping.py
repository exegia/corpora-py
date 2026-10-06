"""Boundary regression checks using tiny generated inputs, never private source text."""

import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from lxml import etree

ROOT = Path(__file__).resolve().parents[4]
MODULE = importlib.util.spec_from_file_location(
    "experiments", ROOT / "scripts/run_corpus_document_experiments.py"
)
experiment = importlib.util.module_from_spec(MODULE)
# dataclass resolves this module by name during import.
sys.modules[MODULE.name] = experiment
MODULE.loader.exec_module(experiment)


class ExtractionMappingTests(unittest.TestCase):
    def assessment(self, index, content="satisfactory", order="satisfactory"):
        return {
            "pageIndex": index,
            "content": content,
            "readingOrder": order,
            "evidence": [
                "Synthetic evaluator evidence for gate regression; not a real-source quality claim"
            ],
        }

    def pdf_document(self, count):
        extraction = experiment.Extraction("gate-test", "")
        extraction.assets = [
            {"name": "synthetic.pdf", "mediaType": "application/pdf", "sha256": "0" * 64}
        ]
        for index in range(count):
            extraction.block("core:page", 0, 0, "synthetic confirmed blank page", str(index))
        return experiment.map_to_corpora(extraction)

    def test_pdf_one_failed_page_rejects_entire_document(self):
        gate = experiment.pdf_gate
        decision = gate.decide(
            "0" * 64, 2, "whole-document", [self.assessment(0), self.assessment(1, "unreadable")]
        )
        self.assertEqual("rejected", decision["status"])
        artifact = gate.artifact(self.pdf_document(2), decision)
        self.assertEqual("unacceptedDiagnostic", artifact["artifactKind"])
        self.assertNotIn("document", artifact)

    def test_pdf_sample_cannot_certify_whole_document(self):
        gate = experiment.pdf_gate
        decision = gate.decide("0" * 64, 10, "bounded-sample", [self.assessment(0)])
        self.assertEqual("pending-review", decision["status"])
        self.assertNotIn("document", gate.artifact(self.pdf_document(1), decision))

    def test_pdf_whole_scope_missing_pages_or_bad_order_is_rejected(self):
        gate = experiment.pdf_gate
        missing = gate.decide("0" * 64, 2, "whole-document", [self.assessment(0)])
        bad_order = gate.decide(
            "0" * 64, 1, "whole-document", [self.assessment(0, order="material-failure")]
        )
        self.assertEqual("rejected", missing["status"])
        self.assertEqual("rejected", bad_order["status"])

    def test_pdf_ocr_run_is_not_acceptance_evidence(self):
        gate = experiment.pdf_gate
        unverified = gate.decide(
            "0" * 64,
            1,
            "whole-document",
            [self.assessment(0, "unverified", "unverified")],
            ocr_used=True,
        )
        unreadable = gate.decide(
            "0" * 64, 1, "whole-document", [self.assessment(0, "unreadable")], ocr_used=True
        )
        self.assertEqual("pending-review", unverified["status"])
        self.assertEqual("rejected", unreadable["status"])

    def test_pdf_parser_failure_is_rejected_with_diagnostic(self):
        from pypdf.errors import PdfReadError

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.pdf"
            path.write_bytes(b"synthetic invalid PDF")
            with patch.object(
                experiment, "PdfReader", side_effect=PdfReadError("synthetic failure")
            ):
                extraction = experiment.extract_pdf(path, "parser-failure")
        self.assertEqual("rejected", extraction.decision["status"])
        self.assertTrue(extraction.decision["extractionFailed"])
        artifact = experiment.pdf_gate.artifact(
            experiment.map_to_corpora(extraction), extraction.decision
        )
        self.assertNotIn("document", artifact)

    def test_pdf_confirmed_blank_page_can_be_preserved(self):
        gate = experiment.pdf_gate
        decision = gate.decide(
            "0" * 64, 1, "whole-document", [self.assessment(0, "blank-confirmed", "unverified")]
        )
        decision = gate.bind(self.pdf_document(1), decision)
        self.assertEqual("accepted", decision["status"])
        self.assertEqual(
            "acceptedImportCandidate", gate.artifact(self.pdf_document(1), decision)["artifactKind"]
        )

    def test_pdf_accepted_decision_cannot_wrap_partial_mapped_pages(self):
        gate = experiment.pdf_gate
        decision = gate.decide(
            "0" * 64, 2, "whole-document", [self.assessment(0), self.assessment(1)]
        )
        decision = gate.bind(self.pdf_document(2), decision)
        with self.assertRaises(ValueError):
            gate.artifact(self.pdf_document(1), decision)
        rejected = gate.decide("0" * 64, 1, "whole-document", [self.assessment(0, "unreadable")])
        rejected["status"] = "accepted"
        with self.assertRaises(ValueError):
            gate.artifact(self.pdf_document(1), rejected)

    def test_usx_zip_pairs_verses_across_paragraphs_and_separates_notes(self):
        source = '<usx version="3.0"><book code="LUK" style="id"/><chapter number="1" style="c" sid="LUK 1"/><para style="q1"><verse number="1" style="v" sid="LUK 1:1"/>Alpha<note style="f" caller="+"><char style="ft">Note.</char></note></para><para style="q2">beta<verse eid="LUK 1:1"/></para><chapter eid="LUK 1"/></usx>'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("safe/LUK.usx", source)
            extraction = experiment.extract_usx_zip(path, "test-usx")
        self.assertEqual("Alpha\nbeta", extraction.text)
        self.assertEqual("Note.", extraction.notes[0]["body"])
        self.assertEqual(1, extraction.metrics["pairedVerses"])
        self.assertEqual(2, extraction.metrics["poetryLines"])
        document = experiment.map_to_corpora(extraction)
        self.assertEqual([], experiment.checker.validate(document))
        self.assertTrue(document["annotations"][0]["body"][0]["marks"])

    def test_usx_archive_traversal_and_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("../LUK.usx", "untrusted data")
            with zipfile.ZipFile(path) as archive, self.assertRaises(ValueError):
                experiment.check_zip_members(archive)
            with zipfile.ZipFile(path, "w") as archive:
                member = zipfile.ZipInfo("LUK.usx")
                member.external_attr = 0o120777 << 16
                archive.writestr(member, "target")
            with zipfile.ZipFile(path) as archive, self.assertRaises(ValueError):
                experiment.check_zip_members(archive)

    def test_plain_preserves_leading_and_interparagraph_whitespace(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plain.txt"
            raw = b"  Alpha\r\n\r\n\tBeta  \r\n"
            path.write_bytes(raw)
            extraction = experiment.extract_plain(path)
            document = experiment.map_to_corpora(extraction)
            self.assertEqual(raw, document["streams"][0]["text"].encode())
            self.assertFalse(extraction.metrics["existingParserReconstructionEqual"])
            self.assertEqual([], experiment.checker.validate(document))

    def test_epub_uses_spine_and_preserves_nested_text_tails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.epub"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "META-INF/container.xml",
                    '<container><rootfiles><rootfile full-path="book.opf"/></rootfiles></container>',
                )
                archive.writestr(
                    "book.opf",
                    '<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/><item id="b" href="b.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="b"/><itemref idref="a"/></spine></package>',
                )
                archive.writestr(
                    "a.xhtml", "<html><body><p>Alpha <em>nested</em> tail.</p></body></html>"
                )
                archive.writestr("b.xhtml", "<html><body><p>Beta first.</p></body></html>")
            extraction = experiment.extract_epub(path)
            self.assertEqual("Beta first.\nAlpha nested tail.", extraction.text)
            self.assertTrue(extraction.metrics["originalSpineDiffersFromManifestOrder"])
            self.assertEqual([], experiment.checker.validate(experiment.map_to_corpora(extraction)))

    def test_tei_selects_one_reading_and_separates_note_body(self):
        source = etree.fromstring(
            b"<ab><w>Alpha</w><lb/><app><rdg><w> chosen</w></rdg><rdg><w> rejected</w></rdg></app><note>Private note</note> tail.</ab>"
        )
        extraction = experiment.Extraction("test-reading", "")
        extraction.text = experiment.walk_xml(source, extraction, "tei-first-reading")
        self.assertEqual("Alpha chosen tail.", extraction.text)
        self.assertEqual({" rejected", "Private note"}, {n["body"] for n in extraction.notes})
        extraction.assets = [
            {"name": "synthetic.xml", "mediaType": "application/xml", "sha256": "0" * 64}
        ]
        document = experiment.map_to_corpora(extraction)
        self.assertEqual([], experiment.checker.validate(document))
        self.assertTrue(any("position" in n for n in document["nodes"]))
        document["nodes"][0]["position"] = {"streamId": document["streams"][0]["id"], "offset": 0}
        self.assertTrue(any(e.startswith("shape:") for e in experiment.checker.validate(document)))

    def test_pdf_empty_page_does_not_become_fabricated_text(self):
        class Page(dict):
            def extract_text(self):
                return ""

        class Reader:
            pages = [Page(), Page()]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "placeholder.pdf"
            path.write_bytes(b"synthetic bytes; PdfReader mocked")
            with patch.object(experiment, "PdfReader", return_value=Reader()):
                extraction = experiment.extract_pdf(path, "empty-pages")
            self.assertEqual("\n", extraction.text)
            self.assertEqual(2, extraction.metrics["emptyExtractedPages"])
            self.assertFalse(extraction.metrics["ocrPerformed"])
            document = experiment.map_to_corpora(extraction)
            self.assertEqual([], experiment.checker.validate(document))
            self.assertEqual(
                2, sum(n["type"] == "core:page" and "position" in n for n in document["nodes"])
            )


if __name__ == "__main__":
    unittest.main()
