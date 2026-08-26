"""Tests for the ``corpora`` terminal CLI (`corpora_py.cli`, issue #188).

The happy path runs the real pipeline end-to-end (plain text -> Text-Fabric
-> ``.cfm`` -> ``.corpus`` -> real `validate_corpus_archive`) -- the same
coverage philosophy as the converter tests, kept cheap with a tiny source.
Everything else (format inference, gate rejection, overwrite refusal, exit
codes) is exercised through `main()` with argv lists, never a subprocess.
"""

import zipfile

import pytest

from corpora_py import cli


def _write_sample(path):
    path.write_text(
        "Sample Title\n\n"
        "Chapter 1\n\n"
        "Hello world this is a paragraph of test content for the cli.\n\n"
        "Another paragraph with more words to convert into an archive.\n"
    )
    return path


class TestConvert:
    def test_converts_plain_text_to_valid_corpus(self, tmp_path, capsys):
        source = _write_sample(tmp_path / "sample.txt")
        output = tmp_path / "out" / "sample.corpus"

        exit_code = cli.main(["convert", str(source), "-o", str(output)])

        assert exit_code == 0
        assert output.is_file()
        assert zipfile.is_zipfile(output)
        # The result path is the one thing printed to stdout (scripting
        # contract); logs go to stderr.
        captured = capsys.readouterr()
        assert captured.out.strip() == str(output)
        assert "Conversion complete." in captured.err
        # The source file is never consumed by the conversion.
        assert source.is_file()

        # And the built archive round-trips through `corpora validate`.
        assert cli.main(["validate", str(output)]) == 0
        assert "Validation: valid" in capsys.readouterr().err

    def test_default_output_is_slugified_title_in_cwd(
        self, tmp_path, monkeypatch, capsys
    ):
        source = _write_sample(tmp_path / "My Great Book.txt")
        monkeypatch.chdir(tmp_path)

        assert cli.main(["convert", str(source)]) == 0

        out = capsys.readouterr().out.strip()
        # PlainTextParser derives the title from the filename stem.
        assert out.endswith("my-great-book.corpus")
        assert (tmp_path / "my-great-book.corpus").is_file()

    def test_refuses_to_overwrite_without_force(self, tmp_path):
        source = _write_sample(tmp_path / "sample.txt")
        output = tmp_path / "sample.corpus"
        output.write_bytes(b"existing")

        with pytest.raises(SystemExit) as excinfo:
            cli.main(["convert", str(source), "-o", str(output)])
        assert "--force" in str(excinfo.value)
        assert output.read_bytes() == b"existing"

        assert cli.main(["convert", str(source), "-o", str(output), "--force"]) == 0
        assert zipfile.is_zipfile(output)

    def test_upload_gate_rejects_non_convertible_bytes(self, tmp_path, capsys):
        # PNG magic bytes with a .txt extension: format inference says
        # plain, the magic-byte gate (issue #173) says image -> exit 2.
        fake = tmp_path / "image.txt"
        fake.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

        with pytest.raises(SystemExit) as excinfo:
            cli.main(["convert", str(fake)])
        assert excinfo.value.code == 2
        assert "image" in capsys.readouterr().err

    def test_missing_source_errors(self, tmp_path):
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["convert", str(tmp_path / "nope.txt")])
        assert "not found" in str(excinfo.value)

    def test_zip_requires_explicit_format(self, tmp_path):
        archive = tmp_path / "dataset.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("member.txt", "content")

        with pytest.raises(SystemExit) as excinfo:
            cli.main(["convert", str(archive)])
        assert "--format" in str(excinfo.value)

    def test_unknown_extension_requires_format(self, tmp_path):
        weird = tmp_path / "book.docx"
        weird.write_bytes(b"whatever")

        with pytest.raises(SystemExit) as excinfo:
            cli.main(["convert", str(weird)])
        assert "--format" in str(excinfo.value)

    def test_converter_error_is_user_facing_exit_1(self, tmp_path, capsys):
        # A ZIP that is not a Text-Fabric dataset: passes the byte gate
        # (it is a real zip) but the tf_zip converter raises its
        # user-facing ValueError -> ConversionError -> exit 1.
        archive = tmp_path / "dataset.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("readme.md", "not a TF dataset")

        exit_code = cli.main(["convert", str(archive), "--format", "tf_zip"])

        assert exit_code == 1
        assert "error:" in capsys.readouterr().err


class TestValidate:
    def test_invalid_archive_exits_1(self, tmp_path, capsys):
        bogus = tmp_path / "bogus.corpus"
        with zipfile.ZipFile(bogus, "w") as zf:
            zf.writestr("not-a-corpus.txt", "nope")

        assert cli.main(["validate", str(bogus)]) == 1
        assert "INVALID" in capsys.readouterr().err

    def test_missing_file_errors(self, tmp_path):
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["validate", str(tmp_path / "nope.corpus")])
        assert "not found" in str(excinfo.value)


class TestFormatInference:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("book.epub", "epub"),
            ("page.HTML", "html"),
            ("doc.xhtml", "html"),
            ("work.tei", "tei"),
            ("data.xml", "xml"),
            ("scan.pdf", "pdf"),
            ("notes.md", "plain"),
            ("plain.txt", "plain"),
        ],
    )
    def test_extension_mapping(self, tmp_path, filename, expected):
        source = tmp_path / filename
        source.write_text("x")
        assert cli._infer_format(source, None).value == expected

    def test_declared_format_wins(self, tmp_path):
        source = tmp_path / "dataset.zip"
        source.write_text("x")
        assert cli._infer_format(source, "tei_zip").value == "tei_zip"
