"""Import an existing Text-Fabric dataset from a ZIP archive."""

from __future__ import annotations

import shutil
import stat
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile, ZipInfo

from ..parsers.schema import CorpusCategory
from ._walker import ConvertedDataset

_MAX_FILES = 10_000
_MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
_REQUIRED_FILES = frozenset({"otype.tf", "oslots.tf"})


def _safe_path(info: ZipInfo) -> PurePosixPath:
    path = PurePosixPath(info.filename)
    mode = info.external_attr >> 16
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe path in Text-Fabric ZIP: {info.filename!r}")
    if stat.S_ISLNK(mode):
        raise ValueError(
            f"Symbolic links are not allowed in Text-Fabric ZIPs: {info.filename!r}"
        )
    if info.flag_bits & 0x1:
        raise ValueError("Encrypted Text-Fabric ZIPs are not supported")
    return path


def _find_dataset_root(files: dict[PurePosixPath, ZipInfo]) -> PurePosixPath:
    candidates: list[PurePosixPath] = []
    for path in files:
        if path.name != "otype.tf":
            continue
        if all(path.parent / required in files for required in _REQUIRED_FILES):
            candidates.append(path.parent)

    if not candidates:
        raise ValueError(
            "ZIP does not contain a Text-Fabric dataset (otype.tf and oslots.tf are required)"
        )
    if len(candidates) > 1:
        roots = ", ".join(str(path) for path in sorted(candidates, key=str))
        raise ValueError(f"ZIP contains multiple Text-Fabric datasets: {roots}")
    return candidates[0]


def convert_tf_zip_to_tf(
    source: str,
    output_dir: str | Path,
    *,
    category: CorpusCategory | None = None,
) -> ConvertedDataset:
    """Extract the single Text-Fabric dataset in ``source`` to ``output_dir``.

    Archive paths, symlinks, member count, and expanded size are validated
    before any bytes are written so a malformed upload cannot escape or fill
    the conversion work directory.

    The dataset arrives pre-built (its section structure is whatever its
    author declared), so a requested `category` is recorded as-is for
    ``manifest.category`` rather than detected (issue #176).
    """
    output_dir = Path(output_dir)

    try:
        with ZipFile(source) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            if len(infos) > _MAX_FILES:
                raise ValueError(
                    f"Text-Fabric ZIP contains more than {_MAX_FILES:,} files"
                )
            if sum(info.file_size for info in infos) > _MAX_UNCOMPRESSED_BYTES:
                raise ValueError("Expanded Text-Fabric ZIP exceeds the 2 GiB limit")

            files = {_safe_path(info): info for info in infos}
            dataset_root = _find_dataset_root(files)
            dataset_files = {
                path: info
                for path, info in files.items()
                if path.is_relative_to(dataset_root) and path.suffix == ".tf"
            }

            output_dir.mkdir(parents=True, exist_ok=False)
            for path, info in dataset_files.items():
                relative = path.relative_to(dataset_root)
                destination = output_dir.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with (
                    archive.open(info) as source_file,
                    destination.open("wb") as output_file,
                ):
                    shutil.copyfileobj(source_file, output_file)
    except BadZipFile as exc:
        raise ValueError("Uploaded file is not a valid ZIP archive") from exc

    return ConvertedDataset.wrap(output_dir, category=category)
