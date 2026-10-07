"""Synthetic EPUB mapping regressions; no attached book text included."""

import copy
import tempfile
import unittest
from pathlib import Path

import check_corpus_document as checker
import convert_epub_to_sql as epub
import corpus_document_sql as sql
from convert_usx_to_sql import Allocations, validate_sql

SOURCE = """<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml"><head><title>Metadata</title></head>
<body><h1 id="section">Heading</h1><p>Quote ' backslash \\ &nbsp; é 😀 <span>inline</span><br/> tail</p>
<table><tbody><tr><td><p>A</p></td><td>B</td></tr></tbody></table><a href="#section">jump</a><img src="../Images/pic.jpg"/></body></html>""".encode()


class EpubTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ids = Allocations(Path(self.temp.name) / "ids.json", epub.digest(SOURCE))

    def tearDown(self):
        self.temp.cleanup()

    def mapped(self):
        root, _, _ = epub.xhtml(SOURCE)
        rev, profile, asset, image, agent, work, edition = (
            self.ids.get(k)
            for k in ("revision", "profile", "asset", "image", "agent", "work", "edition")
        )
        d = {
            "id": self.ids.get("bundle"),
            "specVersion": "0.4.0",
            "requiredCapabilities": [
                "core:text",
                "core:anchors",
                "core:structures",
                "core:positions",
            ],
            "extensions": {},
            **{k: [] for k in sql.FIELDS},
        }
        d["works"] = [{"id": work, "title": "Synthetic"}]
        d["editions"] = [
            {
                "id": edition,
                "title": "Synthetic",
                "workId": work,
                "language": "und",
                "kind": "edition",
            }
        ]
        d["revisions"] = [{"id": rev, "editionId": edition, "sequence": 1, "profileIds": [profile]}]
        d["profiles"] = [
            {
                "id": profile,
                "version": "0.1.0",
                "nodeTypes": ["epub:element", "epub:table", "epub:tableCell", "epub:link"],
                "featureKeys": [],
                "requiredCapabilities": ["core:positions"],
            }
        ]
        d["agents"] = [{"id": agent, "name": "Source declared author", "kind": "person"}]
        d["contributions"] = [
            {
                "id": self.ids.get("contribution"),
                "agentId": agent,
                "role": "core:author",
                "target": {"id": work},
            }
        ]
        d["assets"] = [
            {
                "id": asset,
                "mediaType": "application/xhtml+xml",
                "uri": "synthetic:text",
                "sha256": epub.digest(SOURCE),
            },
            {"id": image, "mediaType": "image/jpeg", "uri": "synthetic:image", "sha256": "0" * 64},
        ]
        resource = epub.Resource(
            d,
            self.ids,
            "Text/main.xhtml",
            root,
            rev,
            {"Text/main.xhtml": asset, "Images/pic.jpg": image},
            0,
            True,
        )
        metrics = resource.convert()
        return d, metrics, resource

    def test_all_body_text_and_metadata_are_separate_and_exact(self):
        d, m, r = self.mapped()
        self.assertEqual([], checker.validate(d))
        body = next(s for s in d["streams"] if s["extensions"]["epub:role"] == "body")["text"]
        self.assertNotIn("Metadata", body)
        self.assertIn("Quote ' backslash \\ \u00a0 é 😀 inline tail", body)
        self.assertTrue(m["bodyTextExact"])
        self.assertTrue(epub.xml_equal(r.root, epub.reconstruct(r.events, d)))
        self.assertEqual(1, m["elements"]["table"])
        self.assertEqual(2, m["elements"]["td"])
        self.assertEqual(1, m["imageReferences"])
        self.assertTrue(r.images[0]["available"])

    def test_sql_round_trip_preserves_author_contribution_and_empty_arrays(self):
        d, _, _ = self.mapped()
        tables = sql.rows(d)
        self.assertEqual(d, sql.restore(tables))
        result = validate_sql("BEGIN;\n" + sql.ddl() + sql.data_sql(tables) + "COMMIT;", tables)
        self.assertTrue(result["allInsertRowsExact"])
        broken = copy.deepcopy(tables)
        broken["contributions"][0]["target_entity_id"] = "urn:synthetic:missing"
        with self.assertRaisesRegex(ValueError, "FK violation"):
            validate_sql("BEGIN;\n" + sql.ddl() + sql.data_sql(broken) + "COMMIT;", broken)

    def test_empty_images_breaks_and_svg_keep_positions(self):
        d, _, _ = self.mapped()
        image = next(n for n in d["nodes"] if n["extensions"]["epub:tag"] == "img")
        br = next(n for n in d["nodes"] if n["extensions"]["epub:tag"] == "br")
        self.assertIn("position", image)
        self.assertIn("assetId", image)
        self.assertIn("position", br)

    def test_source_blocks_keep_table_before_contained_paragraph(self):
        d, _, resource = self.mapped()
        nodes = {n["id"]: n for n in d["nodes"]}
        tags = [nodes[n]["extensions"]["epub:tag"] for n in resource.blocks]
        self.assertEqual(["h1", "p", "table", "p"], tags)
        self.assertEqual("Text/main.xhtml", resource.bindings[0][0])

    def test_entities_safe_doctype_and_unnamespaced_source(self):
        root, entities, removed = epub.xhtml(
            b"<!DOCTYPE html><html><body>A&nbsp;B &amp; C</body></html>"
        )
        self.assertEqual("A\u00a0B & C", root.find("body").text)
        self.assertEqual({"nbsp": 1}, entities)
        self.assertEqual(1, removed)
        with self.assertRaisesRegex(ValueError, "Entity declarations"):
            epub.xhtml(b'<!DOCTYPE html [<!ENTITY x SYSTEM "file:///etc/passwd">]><html/>')
        with self.assertRaisesRegex(ValueError, "Unknown named"):
            epub.xhtml(b"<html><body>&notReal;</body></html>")

    def test_resource_resolution_preserves_fragments_without_fetching(self):
        self.assertEqual(
            "OEBPS/Images/pic.jpg",
            epub.local_resource("OEBPS/Text/main.xhtml", "../Images/pic.jpg#x"),
        )
        self.assertEqual(
            "OEBPS/Text/main.xhtml", epub.local_resource("OEBPS/Text/main.xhtml", "#section")
        )
        self.assertIsNone(
            epub.local_resource("OEBPS/Text/main.xhtml", "https://example.invalid/image")
        )
        with self.assertRaisesRegex(ValueError, "escapes"):
            epub.local_resource("OEBPS/Text/main.xhtml", "../../../outside")


if __name__ == "__main__":
    unittest.main()
