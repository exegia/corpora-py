"""convert_tei_zip_to_tf: member selection, ordering, noise filtering, caps."""

import zipfile
from pathlib import PurePosixPath

import pytest
from admin.converters._tei_zip_to_tf import _is_noise, _tei_members

TEI_DOC = """<?xml version="1.0"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc><titleStmt><title>{title}</title></titleStmt></fileDesc></teiHeader>
  <text><body><div type="chapter"><head>{title}</head><p>Some words here.</p></div></body></text>
</TEI>
"""


def make_zip(path, entries):
    """Write a zip with {name: text} entries."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return str(path)


class TestIsNoise:
    @pytest.mark.parametrize(
        "name", ["__MACOSX/book.xml", "__MACOSX/x/._book.xml", ".DS_Store", "a/.hidden.xml"]
    )
    def test_noise(self, name):
        assert _is_noise(PurePosixPath(name))

    @pytest.mark.parametrize("name", ["book.xml", "corpus/01.tei", "a/b/c.xml"])
    def test_not_noise(self, name):
        assert not _is_noise(PurePosixPath(name))


class TestTeiMembers:
    def _archive(self, tmp_path, entries):
        return zipfile.ZipFile(make_zip(tmp_path / "src.zip", entries))

    def test_selects_tei_and_xml_sorted(self, tmp_path):
        with self._archive(
            tmp_path,
            {
                "02-exodus.xml": "<TEI/>",
                "01-genesis.tei": "<TEI/>",
                "readme.txt": "not a document",
            },
        ) as archive:
            names = [info.filename for info in _tei_members(archive)]
        assert names == ["01-genesis.tei", "02-exodus.xml"]

    def test_noise_entries_ignored(self, tmp_path):
        with self._archive(
            tmp_path,
            {"book.xml": "<TEI/>", "__MACOSX/._book.xml": "fork", ".DS_Store": ""},
        ) as archive:
            names = [info.filename for info in _tei_members(archive)]
        assert names == ["book.xml"]

    def test_no_tei_documents_raises(self, tmp_path):
        with self._archive(tmp_path, {"notes.txt": "hello"}) as archive:
            with pytest.raises(ValueError, match="does not contain any TEI documents"):
                _tei_members(archive)

    def test_traversal_rejected(self, tmp_path):
        with self._archive(tmp_path, {"../escape.xml": "<TEI/>"}) as archive:
            with pytest.raises(ValueError, match="Unsafe path"):
                _tei_members(archive)


class TestConvert:
    def test_parses_each_member_into_a_document(self, tmp_path, monkeypatch):
        # Intercept the walk: converting for real needs text-fabric's full
        # dataset machinery; this test pins the contract that every member
        # document is parsed (in order) and handed to convert_documents.
        import admin.converters._tei_zip_to_tf as module

        captured = {}

        def fake_convert_documents(documents, output_dir, **kwargs):
            captured["titles"] = [doc.metadata.title for doc in documents]
            captured["kwargs"] = kwargs
            return output_dir

        monkeypatch.setattr(module, "convert_documents", fake_convert_documents)

        src = make_zip(
            tmp_path / "corpus.zip",
            {
                "b-second.xml": TEI_DOC.format(title="Second"),
                "a-first.xml": TEI_DOC.format(title="First"),
            },
        )
        module.convert_tei_zip_to_tf(src, tmp_path / "out")

        assert captured["titles"] == ["First", "Second"]
        assert captured["kwargs"]["root_type"] == "text"
        assert captured["kwargs"]["format_value"] == "tei"

    def test_not_a_zip_raises(self, tmp_path):
        bogus = tmp_path / "bogus.zip"
        bogus.write_bytes(b"definitely not a zip")
        from admin.converters._tei_zip_to_tf import convert_tei_zip_to_tf

        with pytest.raises(ValueError, match="not a valid ZIP archive"):
            convert_tei_zip_to_tf(str(bogus), tmp_path / "out")
