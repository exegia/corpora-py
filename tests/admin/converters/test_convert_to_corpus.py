"""`_validate_archive` enforces the `.corpus` archive-layout contract.

A `.corpus` archive must carry `manifest.yml`, `toc.yml`, and a `corpora/`
directory (see `packages/admin/src/admin/converters/CLAUDE.md`). A converter
that produces a zip missing any of these is broken and must never reach a
client's library -- `convert_to_corpus` validates the archive it just wrote
and raises `CorpusArchiveError` on a miss (issue #108's "Reject / 422 any
converter that cannot produce the archive layout").
"""

import importlib
import zipfile

import pytest
import yaml

# `admin.converters.__init__` re-exports the *function* `convert_to_corpus`,
# which shadows the submodule of the same name (see `test_git_snapshot.py`
# for the same import workaround). `import_module` reaches the module itself.
mod = importlib.import_module("admin.converters.convert_to_corpus")


def _write_zip(path, members: dict[str, bytes]) -> None:
    """Build a zip with the given `members` (path -> bytes)."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, body in members.items():
            zf.writestr(name, body)


class TestValidateArchive:
    def test_accepts_full_layout(self, tmp_path):
        archive = tmp_path / "good.corpus"
        _write_zip(
            archive,
            {
                "manifest.yml": b"uid: x\n",
                "toc.yml": b"uid: y\n",
                "corpora/otype.tf": b"node",
                "corpora/.cfm/cache": b"cache",
            },
        )
        # Must not raise.
        mod._validate_archive(archive)

    def test_accepts_corpora_directory_member(self, tmp_path):
        """Some zip writers emit a separate `corpora/` directory entry; the
        validator accepts both that form and the `corpora/<file>` form."""
        archive = tmp_path / "good-dir-entry.corpus"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("manifest.yml", b"uid: x\n")
            zf.writestr("toc.yml", b"uid: y\n")
            zf.writestr(zipfile.ZipInfo("corpora/"), b"")
        mod._validate_archive(archive)  # must not raise

    def test_missing_manifest_raises(self, tmp_path):
        archive = tmp_path / "missing-manifest.corpus"
        _write_zip(
            archive,
            {"toc.yml": b"uid: y\n", "corpora/otype.tf": b"node"},
        )
        with pytest.raises(mod.CorpusArchiveError) as excinfo:
            mod._validate_archive(archive)
        assert "manifest.yml" in str(excinfo.value)

    def test_missing_toc_raises(self, tmp_path):
        archive = tmp_path / "missing-toc.corpus"
        _write_zip(
            archive,
            {"manifest.yml": b"uid: x\n", "corpora/otype.tf": b"node"},
        )
        with pytest.raises(mod.CorpusArchiveError) as excinfo:
            mod._validate_archive(archive)
        assert "toc.yml" in str(excinfo.value)

    def test_missing_corpora_dir_raises(self, tmp_path):
        archive = tmp_path / "missing-corpora.corpus"
        _write_zip(
            archive,
            {"manifest.yml": b"uid: x\n", "toc.yml": b"uid: y\n"},
        )
        with pytest.raises(mod.CorpusArchiveError) as excinfo:
            mod._validate_archive(archive)
        assert "corpora/" in str(excinfo.value)

    def test_lists_every_missing_member(self, tmp_path):
        """One error message names every breach, not just the first."""
        archive = tmp_path / "empty.corpus"
        _write_zip(archive, {"readme.txt": b"hi"})
        with pytest.raises(mod.CorpusArchiveError) as excinfo:
            mod._validate_archive(archive)
        message = str(excinfo.value)
        assert "manifest.yml" in message
        assert "toc.yml" in message
        assert "corpora/" in message


class TestCorpusArchiveErrorIsExported:
    def test_importable_from_converters_package(self):
        from admin.converters import CorpusArchiveError  # noqa: F401

    def test_subclass_of_exception(self):
        assert issubclass(mod.CorpusArchiveError, Exception)


class TestHistoryYml:
    """convert_to_corpus writes history.yml and no longer packages .git/."""

    def test_archive_contains_v1_history_without_git(self, tmp_path):
        from admin.converters._text_to_tf import convert_text_to_tf

        src = tmp_path / "mini.txt"
        src.write_text("Hello world.\n\nSecond paragraph has more words.")
        tf_dir = convert_text_to_tf(str(src), tmp_path / "tf")
        archive = mod.convert_to_corpus(tf_dir, tmp_path / "mini.corpus", name="Mini")

        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            assert "history.yml" in names
            assert "manifest.yml" in names
            assert not any(n == ".git/" or n.startswith(".git/") for n in names)
            history = yaml.safe_load(zf.read("history.yml"))
            manifest = yaml.safe_load(zf.read("manifest.yml"))

        versions = history["versions"]
        assert len(versions) == 1
        row = versions[0]
        assert row["id"] == "v1.0"
        assert row["label"] == "v1.0"
        assert row["title"] == "Converted"
        assert row["current"] is True
        assert row["at"] == manifest["written_date"]
        assert row["snapshot_key"] is None
        assert row["author"] is None
        assert row["approved_by"] is None
        assert row["notes"] == []
        assert {f["path"] for f in row["files"]} == {
            "manifest.yml",
            "toc.yml",
            "corpora/",
        }
        assert all(f["kind"] == "added" for f in row["files"])

    def test_history_stamps_author_sub_when_provided(self, tmp_path):
        from admin.converters._text_to_tf import convert_text_to_tf

        src = tmp_path / "mini.txt"
        src.write_text("Hello world.\n")
        tf_dir = convert_text_to_tf(str(src), tmp_path / "tf")
        archive = mod.convert_to_corpus(
            tf_dir,
            tmp_path / "mini.corpus",
            name="Mini",
            author_sub="user-1",
        )
        with zipfile.ZipFile(archive) as zf:
            history = yaml.safe_load(zf.read("history.yml"))
        actor = history["versions"][0]["author"]
        assert actor == {"sub": "user-1"}
        assert history["versions"][0]["approved_by"] == actor

    def test_history_does_not_invent_a_user(self, tmp_path):
        from admin.converters._text_to_tf import convert_text_to_tf

        src = tmp_path / "mini.txt"
        src.write_text("Hello world.\n")
        tf_dir = convert_text_to_tf(str(src), tmp_path / "tf")
        archive = mod.convert_to_corpus(
            tf_dir, tmp_path / "mini.corpus", name="Mini", author_sub="  "
        )
        with zipfile.ZipFile(archive) as zf:
            history = yaml.safe_load(zf.read("history.yml"))
        assert history["versions"][0]["author"] is None
