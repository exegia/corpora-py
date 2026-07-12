from pathlib import Path
from zipfile import ZipFile

import pytest

from admin.converters import convert_tf_zip_to_tf


def _write_zip(path: Path, members: dict[str, str]) -> None:
    with ZipFile(path, "w") as archive:
        for name, contents in members.items():
            archive.writestr(name, contents)


def test_imports_nested_text_fabric_dataset(tmp_path: Path) -> None:
    source = tmp_path / "dataset.zip"
    _write_zip(
        source,
        {
            "project/README.md": "ignored",
            "project/tf/2022/otype.tf": "@node\n",
            "project/tf/2022/oslots.tf": "@edge\n",
            "project/tf/2022/text.tf": "text",
        },
    )

    output = convert_tf_zip_to_tf(str(source), tmp_path / "output")

    assert sorted(path.name for path in output.iterdir()) == [
        "oslots.tf",
        "otype.tf",
        "text.tf",
    ]
    assert (output / "text.tf").read_text() == "text"


def test_rejects_archive_without_text_fabric_dataset(tmp_path: Path) -> None:
    source = tmp_path / "invalid.zip"
    _write_zip(source, {"README.md": "not a dataset"})

    with pytest.raises(ValueError, match="otype.tf and oslots.tf"):
        convert_tf_zip_to_tf(str(source), tmp_path / "output")


def test_rejects_path_traversal_before_extracting(tmp_path: Path) -> None:
    source = tmp_path / "unsafe.zip"
    _write_zip(
        source,
        {
            "dataset/otype.tf": "@node\n",
            "dataset/oslots.tf": "@edge\n",
            "../escaped.tf": "nope",
        },
    )

    output = tmp_path / "output"
    with pytest.raises(ValueError, match="Unsafe path"):
        convert_tf_zip_to_tf(str(source), output)

    assert not output.exists()
    assert not (tmp_path.parent / "escaped.tf").exists()
