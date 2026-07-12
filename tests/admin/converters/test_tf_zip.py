"""convert_tf_zip_to_tf: zip-slip, symlink, encryption, bomb caps, dataset root."""

import stat
import zipfile
from pathlib import PurePosixPath

import pytest

from admin.converters._tf_zip_to_tf import (
    _MAX_FILES,
    _find_dataset_root,
    _safe_path,
    convert_tf_zip_to_tf,
)


def make_zip(path, entries):
    """Write a zip with {name: bytes} entries."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return str(path)


def _info(filename, *, symlink=False, encrypted=False):
    info = zipfile.ZipInfo(filename)
    if symlink:
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
    if encrypted:
        info.flag_bits |= 0x1
    return info


class TestSafePath:
    def test_normal_path_ok(self):
        assert _safe_path(_info("data/otype.tf")) == PurePosixPath("data/otype.tf")

    @pytest.mark.parametrize("bad", ["/etc/passwd", "../escape.tf", "a/../../b.tf"])
    def test_traversal_rejected(self, bad):
        with pytest.raises(ValueError, match="Unsafe path"):
            _safe_path(_info(bad))

    def test_symlink_rejected(self):
        with pytest.raises(ValueError, match="Symbolic links"):
            _safe_path(_info("link.tf", symlink=True))

    def test_encrypted_rejected(self):
        with pytest.raises(ValueError, match="Encrypted"):
            _safe_path(_info("otype.tf", encrypted=True))


class TestFindDatasetRoot:
    def _files(self, *names):
        return {PurePosixPath(n): zipfile.ZipInfo(n) for n in names}

    def test_single_dataset_found(self):
        files = self._files("ds/otype.tf", "ds/oslots.tf", "ds/text.tf")
        assert _find_dataset_root(files) == PurePosixPath("ds")

    def test_root_level_dataset(self):
        files = self._files("otype.tf", "oslots.tf")
        assert _find_dataset_root(files) == PurePosixPath(".")

    def test_no_dataset_raises(self):
        with pytest.raises(ValueError, match="does not contain a Text-Fabric dataset"):
            _find_dataset_root(self._files("readme.md", "text.tf"))

    def test_otype_without_oslots_not_a_dataset(self):
        with pytest.raises(ValueError):
            _find_dataset_root(self._files("ds/otype.tf", "ds/readme.md"))

    def test_multiple_datasets_raise(self):
        files = self._files("a/otype.tf", "a/oslots.tf", "b/otype.tf", "b/oslots.tf")
        with pytest.raises(ValueError, match="multiple Text-Fabric datasets"):
            _find_dataset_root(files)


class TestConvert:
    def test_extracts_only_tf_files_under_root(self, tmp_path):
        src = make_zip(
            tmp_path / "up.zip",
            {
                "ds/otype.tf": b"@node\n",
                "ds/oslots.tf": b"@edge\n",
                "ds/notes.txt": b"skip me",
                "outside.tf": b"skip me too",
            },
        )
        out = convert_tf_zip_to_tf(src, tmp_path / "out")
        extracted = sorted(p.name for p in out.iterdir())
        assert extracted == ["oslots.tf", "otype.tf"]
        assert (out / "otype.tf").read_bytes() == b"@node\n"

    def test_not_a_zip_raises_valueerror(self, tmp_path):
        bad = tmp_path / "fake.zip"
        bad.write_bytes(b"definitely not a zip")
        with pytest.raises(ValueError, match="not a valid ZIP"):
            convert_tf_zip_to_tf(str(bad), tmp_path / "out")

    def test_too_many_files_rejected_before_extraction(self, tmp_path, monkeypatch):
        monkeypatch.setattr("admin.converters._tf_zip_to_tf._MAX_FILES", 2)
        src = make_zip(
            tmp_path / "many.zip",
            {"ds/otype.tf": b"x", "ds/oslots.tf": b"x", "ds/extra.tf": b"x"},
        )
        with pytest.raises(ValueError, match="more than"):
            convert_tf_zip_to_tf(src, tmp_path / "out")
        assert not (tmp_path / "out").exists()

    def test_uncompressed_size_cap(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "admin.converters._tf_zip_to_tf._MAX_UNCOMPRESSED_BYTES", 10
        )
        src = make_zip(
            tmp_path / "big.zip",
            {"ds/otype.tf": b"x" * 20, "ds/oslots.tf": b"x"},
        )
        with pytest.raises(ValueError, match="exceeds"):
            convert_tf_zip_to_tf(src, tmp_path / "out")

    def test_traversal_entry_aborts_whole_import(self, tmp_path):
        src = make_zip(
            tmp_path / "slip.zip",
            {"ds/otype.tf": b"x", "ds/oslots.tf": b"x", "../evil.tf": b"x"},
        )
        with pytest.raises(ValueError, match="Unsafe path"):
            convert_tf_zip_to_tf(src, tmp_path / "out")
        assert not (tmp_path / "out").exists()

    def test_existing_output_dir_rejected(self, tmp_path):
        src = make_zip(
            tmp_path / "ok.zip", {"otype.tf": b"x", "oslots.tf": b"x"}
        )
        out = tmp_path / "out"
        out.mkdir()
        with pytest.raises(FileExistsError):
            convert_tf_zip_to_tf(src, out)

    def test_max_files_constant_is_sane(self):
        assert _MAX_FILES == 10_000
