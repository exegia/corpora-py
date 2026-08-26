"""convert_tf_zip_to_tf: zip-slip, symlink, encryption, bomb caps, dataset root."""

import stat
import zipfile
from pathlib import PurePosixPath

import pytest
from admin.converters._tf_zip_to_tf import (
    _MAX_FILES,
    _find_dataset_root,
    _parse_tf_version,
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
        assert _find_dataset_root(files) == (PurePosixPath("ds"), [])

    def test_root_level_dataset(self):
        files = self._files("otype.tf", "oslots.tf")
        assert _find_dataset_root(files) == (PurePosixPath("."), [])

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

    def test_versioned_layout_picks_latest(self):
        files = self._files(
            "moby/0.1/otype.tf",
            "moby/0.1/oslots.tf",
            "moby/0.2pre/otype.tf",
            "moby/0.2pre/oslots.tf",
            "moby/0.2/otype.tf",
            "moby/0.2/oslots.tf",
        )
        root, warnings = _find_dataset_root(files)
        assert root == PurePosixPath("moby/0.2")
        assert warnings == ["Selected dataset version 0.2 (also found: 0.1, 0.2pre)"]

    def test_versioned_layout_multi_component(self):
        files = self._files(
            "ds/1.7.3/otype.tf",
            "ds/1.7.3/oslots.tf",
            "ds/1.10/otype.tf",
            "ds/1.10/oslots.tf",
        )
        root, _ = _find_dataset_root(files)
        assert root == PurePosixPath("ds/1.10")

    def test_version_dirs_under_different_parents_still_raise(self):
        files = self._files(
            "a/0.1/otype.tf", "a/0.1/oslots.tf", "b/0.2/otype.tf", "b/0.2/oslots.tf"
        )
        with pytest.raises(ValueError, match="multiple Text-Fabric datasets"):
            _find_dataset_root(files)

    def test_non_version_siblings_still_raise(self):
        files = self._files(
            "ds/0.1/otype.tf",
            "ds/0.1/oslots.tf",
            "ds/extras/otype.tf",
            "ds/extras/oslots.tf",
        )
        with pytest.raises(ValueError, match="multiple Text-Fabric datasets"):
            _find_dataset_root(files)


class TestParseTfVersion:
    def test_ordering_matches_text_fabric(self):
        ordered = ["0.1", "0.2pre", "0.2", "0.2.1", "0.10", "1.0pre", "1.0", "1.7.3"]
        keys = [_parse_tf_version(name) for name in ordered]
        assert all(key is not None for key in keys)
        assert keys == sorted(keys)  # type: ignore[type-var]

    @pytest.mark.parametrize("bad", ["extras", "v0.2", "0.2-pre", "", "final", "0..2"])
    def test_non_versions_rejected(self, bad):
        assert _parse_tf_version(bad) is None


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

    def test_versioned_zip_extracts_latest_with_warning(self, tmp_path):
        src = make_zip(
            tmp_path / "versioned.zip",
            {
                "moby/0.1/otype.tf": b"@node old\n",
                "moby/0.1/oslots.tf": b"@edge old\n",
                "moby/0.2pre/otype.tf": b"@node pre\n",
                "moby/0.2pre/oslots.tf": b"@edge pre\n",
                "moby/0.2/otype.tf": b"@node new\n",
                "moby/0.2/oslots.tf": b"@edge new\n",
            },
        )
        out = convert_tf_zip_to_tf(src, tmp_path / "out")
        extracted = sorted(p.name for p in out.iterdir())
        assert extracted == ["oslots.tf", "otype.tf"]
        assert (out / "otype.tf").read_bytes() == b"@node new\n"
        assert out.warnings == [
            "Selected dataset version 0.2 (also found: 0.1, 0.2pre)"
        ]

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
