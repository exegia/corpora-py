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
