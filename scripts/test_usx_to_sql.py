"""Synthetic regressions; no private source contents included."""

import copy
import tempfile
import unittest
import zipfile
from pathlib import Path

import check_corpus_document as checker
import convert_usx_to_sql as converter
import corpus_document_sql as sql

SOURCE = b"""<usx version="3.0">
  <book code="TST" style="id">Synthetic book</book>
  <chapter number="1" style="c" sid="TST 1"/>
  <para style="p"><verse number="1" style="v" sid="TST 1:1"/>Apostrophe ' backslash \\ $$ <note style="f" caller="+"><char style="fr">1:1 </char><char style="ft">note ' \\ $$</char></note> and </para>
  <para style="q">overlap <verse eid="TST 1:1"/><verse number="2" style="v" sid="TST 1:2"/>second<verse eid="TST 1:2"/></para>
  <para style="b"/>
  <chapter eid="TST 1"/>
</usx>"""


def synthetic(ids):
    d = {
        "id": ids.get("bundle"),
        "specVersion": "0.4.0",
        "requiredCapabilities": [
            "core:text",
            "core:anchors",
            "core:structures",
            "core:positions",
            "core:annotations",
            "core:references",
        ],
        "extensions": {},
        **{k: [] for k in sql.FIELDS},
    }
    profile, agent, asset, imported = (ids.get(k) for k in ("profile", "agent", "asset", "import"))
    d["profiles"] = [
        {
            "id": profile,
            "version": "0.1.0",
            "nodeTypes": ["usx:bookMetadata", "usx:poetryLine", "usx:characterSpan"],
            "featureKeys": [],
            "requiredCapabilities": ["core:positions"],
        }
    ]
    d["agents"] = [{"id": agent, "name": "Synthetic converter", "kind": "software"}]
    d["assets"] = [
        {
            "id": asset,
            "uri": "synthetic:fixture",
            "sha256": converter.digest(SOURCE),
            "mediaType": "application/vnd.usx+xml",
        }
    ]
    d["imports"] = [
        {
            "id": imported,
            "assetIds": [asset],
            "adapter": "synthetic",
            "adapterVersion": "0.1.0",
            "agentId": agent,
            "report": [
                {"aspect": "synthetic", "status": "preserved", "detail": "Synthetic fixture"}
            ],
        }
    ]
    # Additional Unicode including a combining mark and supplementary scalar.
    raw = SOURCE.replace(b"second", "δεύτερο e\u0301 😀".encode())
    book = converter.Book(
        d, ids, "fixture.usx", converter.parse_xml(raw), asset, "und", agent, imported, profile
    )
    metrics = book.convert()
    d["collections"] = [
        {
            "id": ids.get("collection"),
            "title": "Synthetic",
            "members": [{"order": 0, "workId": book.work, "editionId": book.edition}],
        }
    ]
    return d, metrics, book


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.ids = converter.Allocations(self.path / "ids.json", converter.digest(SOURCE))

    def tearDown(self):
        self.temp.cleanup()

    def test_full_text_notes_whitespace_and_xml_round_trip(self):
        d, m, b = synthetic(self.ids)
        self.assertEqual([], checker.validate(d))
        self.assertTrue(m["decodedXmlRoundTripExact"])
        self.assertEqual(
            (1, 2, 1, 3, 2),
            (m["chapters"], m["verses"], m["notes"], m["paragraphs"], m["characters"]),
        )
        self.assertEqual(1, m["versesCrossingParagraphs"])
        self.assertNotIn("note '", d["streams"][0]["text"])
        self.assertEqual("1:1 note ' \\ $$", d["annotations"][0]["body"][0]["text"])
        self.assertIn("e\u0301 😀", d["streams"][0]["text"])
        self.assertTrue(
            converter.xml_equal(b.root, converter.reconstruct_xml(d, d["revisions"][0]))
        )
        self.assertTrue(
            any(
                "position" in n and n["extensions"]["usx:attributes"].get("style") == "b"
                for n in d["nodes"]
            )
        )

    def test_normalized_and_sql_parsed_values_exact(self):
        d, _, _ = synthetic(self.ids)
        tables = sql.rows(d)
        self.assertEqual(d, sql.restore(tables))
        script = "BEGIN;\n" + sql.ddl() + sql.data_sql(tables) + "COMMIT;"
        self.assertTrue(converter.validate_sql(script, tables)["allInsertRowsExact"])
        # SQL parser must not turn strings into executable statements.
        attacked = copy.deepcopy(tables)
        attacked["streams"][0]["text"] += "'); DROP SCHEMA public CASCADE; -- \\ $$"
        self.assertTrue(
            converter.validate_sql(
                "BEGIN;\n" + sql.ddl() + sql.data_sql(attacked) + "COMMIT;", attacked
            )["allInsertRowsExact"]
        )

    def test_member_array_order_survives_database_row_reordering(self):
        d, _, _ = synthetic(self.ids)
        tables = sql.rows(d)
        tables["structure_members"].reverse()
        self.assertEqual(d, sql.restore(tables))

    def test_persistent_allocations_not_derived_from_source(self):
        first = self.ids.get("source-local-key")
        self.ids.save()
        second = converter.Allocations(self.path / "ids.json", converter.digest(SOURCE))
        self.assertEqual(first, second.get("source-local-key"))
        third = converter.Allocations(self.path / "different.json", converter.digest(SOURCE))
        self.assertNotEqual(first, third.get("source-local-key"))
        with self.assertRaisesRegex(ValueError, "another immutable source"):
            converter.Allocations(self.path / "ids.json", "0" * 64)

    def test_unclosed_milestone_is_rejected(self):
        d, _, b = synthetic(self.ids)
        root = converter.parse_xml(SOURCE.replace(b'<verse eid="TST 1:2"/>', b""))
        book = converter.Book(
            d,
            self.ids,
            "broken.usx",
            root,
            b.asset_id,
            "und",
            b.agent_id,
            d["imports"][0]["id"],
            d["profiles"][0]["id"],
        )
        with self.assertRaisesRegex(ValueError, "open verse"):
            book.convert()

    def test_unsafe_zip_and_dtd_rejected(self):
        p = self.path / "bad.zip"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("../book.usx", SOURCE)
        with self.assertRaisesRegex(ValueError, "Unsafe archive"):
            converter.archive_members(p)
        with self.assertRaisesRegex(ValueError, "DTD"):
            converter.parse_xml(b'<!DOCTYPE usx [<!ENTITY x "bad">]><usx/>')

    def test_unknown_semantics_not_silently_dropped(self):
        d, _, b = synthetic(self.ids)
        root = converter.parse_xml(SOURCE.replace(b"</usx>", b'<ref loc="TST 1:1">ref</ref></usx>'))
        with self.assertRaisesRegex(ValueError, "Unmapped"):
            converter.Book(
                d,
                self.ids,
                "unsupported.usx",
                root,
                b.asset_id,
                "und",
                b.agent_id,
                d["imports"][0]["id"],
                d["profiles"][0]["id"],
            )
        changed = copy.deepcopy(d)
        changed["relations"] = [{"id": "synthetic:unmapped"}]
        with self.assertRaisesRegex(ValueError, "Unmapped SQL"):
            sql.rows(changed)

    def test_scalar_bounds_and_cross_revision_rejected(self):
        d, _, _ = synthetic(self.ids)
        changed = copy.deepcopy(d)
        changed["anchors"][0]["segments"][0]["end"] = len(d["streams"][0]["text"]) + 1
        self.assertIn("anchor:bounds", checker.validate(changed))
        changed = copy.deepcopy(d)
        changed["streams"][0]["revisionId"] = "urn:synthetic:other-revision"
        self.assertIn("anchor:revision", checker.validate(changed))

    def test_postgresql_unsupported_nul_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            sql.literal("nul\x00text")

    def test_static_foreign_key_and_unique_checks_reject_bad_rows(self):
        d, _, _ = synthetic(self.ids)
        tables = sql.rows(d)
        tables["anchor_segments"][0]["stream_id"] = "urn:synthetic:missing"
        with self.assertRaisesRegex(ValueError, "FK violation"):
            converter.validate_sql(
                "BEGIN;\n" + sql.ddl() + sql.data_sql(tables) + "COMMIT;", tables
            )
        tables = sql.rows(d)
        tables["streams"].append(copy.deepcopy(tables["streams"][0]))
        with self.assertRaisesRegex(ValueError, "unique key"):
            converter.validate_sql(
                "BEGIN;\n" + sql.ddl() + sql.data_sql(tables) + "COMMIT;", tables
            )

    def test_freeze_guards_include_truncate_for_every_table(self):
        from pglast import ast, parse_sql

        statements = [s.stmt for s in parse_sql(sql.ddl())]
        tables = {s.relation.relname for s in statements if isinstance(s, ast.CreateStmt)}
        guarded = {
            s.relation.relname
            for s in statements
            if isinstance(s, ast.CreateTrigStmt) and not s.row and s.events & 32
        }
        self.assertEqual(tables, guarded)

    def test_schema_creates_tables_before_foreign_keys(self):
        from pglast import ast, parse_sql

        statements = parse_sql(sql.ddl())
        created = set()
        for raw in statements:
            node = raw.stmt
            if isinstance(node, ast.CreateStmt):
                created.add(node.relation.relname)
            elif isinstance(node, ast.AlterTableStmt):
                self.assertIn(node.relation.relname, created)
                for command in node.cmds:
                    self.assertIn(command.def_.pktable.relname, created)


if __name__ == "__main__":
    unittest.main()
