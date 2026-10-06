"""Focused checker tests; run with uv and jsonschema, no application services."""

import copy
import hashlib
import importlib.util
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Same layout in the checkout and portable bundle.
SPEC = importlib.util.spec_from_file_location(
    "checker", HERE.parents[2] / "scripts/check_corpus_document.py"
)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def fixture(name):
    return json.loads((HERE / "fixtures" / name).read_text())


class ConformanceTests(unittest.TestCase):
    def test_usx_projection_assets_and_overlapping_coverage(self):
        for name in ("usx-scripture", "usx-peripheral"):
            document = fixture(name + ".valid.json")
            data = (HERE / "fixtures" / (name + ".usx")).read_bytes()
            self.assertEqual("usx", ET.fromstring(data).tag)
            self.assertEqual(document["assets"][0]["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual([], checker.validate(document))
            self.assertIn(
                "capability:unsupported-required",
                checker.validate(document, checker.CAPABILITIES - {"core:positions"}),
            )
        document = fixture("usx-scripture.valid.json")
        by_node = {n["id"]: n for n in document["nodes"]}
        by_anchor = {a["id"]: a for a in document["anchors"]}

        def span(name):
            return by_anchor[by_node["urn:usx-example:" + name]["anchorId"]]["segments"][0]

        verse, line1, line2 = span("verse"), span("q1"), span("q2")
        self.assertEqual((verse["start"], verse["end"]), (line1["start"], line2["end"]))
        self.assertEqual(line1["end"], line2["start"])
        self.assertEqual("GEN 1:1-2", document["schemes"][0]["entries"][0]["key"])
        self.assertNotIn("A note.", document["streams"][0]["text"])

    def test_all_fixtures_and_offline_schemas(self):
        checker.check_fixtures()

    def test_reader_capabilities_are_enforced(self):
        document = fixture("tf-discontinuous.valid.json")
        self.assertIn("capability:unsupported-required", checker.validate(document, {"core:text"}))
        self.assertEqual([], checker.validate(document))

    def test_loaded_external_target_is_checked(self):
        document = fixture("bible-numbering.valid.json")
        external_id = "urn:example:remote-bundle"
        missing = checker.validate(document, external={external_id: {"id": external_id}})
        self.assertIn("endpoint:missing-external", missing)
        external = {"id": external_id, "nodes": [{"id": "urn:example:remote-node"}]}
        self.assertEqual([], checker.validate(document, external={external_id: external}))

    def test_range_uses_order_and_rejects_forged_targets(self):
        document = fixture("quran-edition.valid.json")
        bad = copy.deepcopy(document)
        bad["resolutions"][0]["targetIds"].reverse()
        self.assertIn("resolution:targets", checker.validate(bad))
        self.assertEqual([], checker.validate(document))

    def test_namespaced_extension_and_control_text_survive_xml(self):
        spec = importlib.util.spec_from_file_location("codec", HERE / "xml_codec.py")
        codec = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(codec)
        document = fixture("minimal-document.valid.json")
        document["extensions"]["future:data"] = {
            "control\x00": "\x00\r\n😀",
            "values": [False, None, 1.25],
        }
        self.assertEqual(document, codec.decode(codec.encode(document)))
        with self.assertRaises(ValueError):
            codec.decode(b"<!DOCTYPE x [<!ENTITY e 'x'>]><x/>")
        with self.assertRaises(ValueError):
            codec.decode(
                b'<document xmlns="urn:corpora:corpus-document:xml:0.4.0"><number>1e999</number></document>'
            )

    def test_surrogate_and_unknown_core_type_fail(self):
        document = fixture("single-page.valid.json")
        document["streams"][0]["text"] = "\ud800" * 5
        self.assertIn("text:surrogate", checker.validate(document))
        document = fixture("single-page.valid.json")
        document["nodes"][0]["type"] = "core:invented"
        self.assertIn("profile:undeclared-type", checker.validate(document))


if __name__ == "__main__":
    unittest.main()
