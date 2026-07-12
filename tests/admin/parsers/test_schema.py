"""Shared schema: tokenize, models, read_source_bytes."""

import io

import pytest
from admin.parsers.schema import (
    Document,
    DocumentMetadata,
    SourceFormat,
    Token,
    Unit,
    read_source_bytes,
    tokenize,
)


class TestTokenize:
    def test_captures_interword_whitespace_as_after(self):
        tokens = tokenize("Hello  world\nagain")
        assert [(t.text, t.after) for t in tokens] == [
            ("Hello", "  "),
            ("world", "\n"),
            ("again", ""),
        ]

    def test_reconstructs_original_text(self):
        text = "In the  beginning\tGod\ncreated"
        assert "".join(t.text + t.after for t in tokenize(text)) == text

    def test_trailing_whitespace_kept_on_last_token(self):
        tokens = tokenize("word \n")
        assert tokens[-1].after == " \n"

    @pytest.mark.parametrize("empty", [None, "", "   "])
    def test_empty_or_blank_input(self, empty):
        if empty and empty.strip() == "":
            # whitespace-only: no \S+ matches
            assert tokenize(empty) == []
        else:
            assert tokenize(empty) == []

    def test_punctuation_stays_attached_to_word(self):
        tokens = tokenize("Hello, world!")
        assert tokens[0].text == "Hello,"
        assert tokens[1].text == "world!"


class TestModels:
    def test_unit_recursion_round_trip(self):
        unit = Unit(
            type="chapter",
            id="1",
            children=[Unit(type="p", tokens=[Token(text="hi", after=" ")])],
        )
        dumped = unit.model_dump()
        assert Unit.model_validate(dumped) == unit

    def test_document_defaults(self):
        doc = Document(metadata=DocumentMetadata(source_format=SourceFormat.PLAIN))
        assert doc.units == []
        assert doc.metadata.creators == []
        assert doc.metadata.extra == {}

    def test_token_after_defaults_empty(self):
        assert Token(text="x").after == ""


class TestReadSourceBytes:
    def test_local_file(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_bytes(b"payload")
        assert read_source_bytes(str(f)) == b"payload"

    def test_http_url_uses_urlopen(self, monkeypatch):
        import urllib.request

        class FakeResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(
            urllib.request, "urlopen", lambda url: FakeResponse(b"remote-bytes")
        )
        assert read_source_bytes("https://example.test/doc.txt") == b"remote-bytes"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_source_bytes(str(tmp_path / "nope.txt"))
