"""Import an existing Text-Fabric dataset from a ZIP archive."""

from __future__ import annotations

import re
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


_VERSION_COMPONENT = re.compile(r"^(\d+)([A-Za-z][A-Za-z0-9]*)?$")


def _parse_tf_version(name: str) -> tuple[tuple[int, int, str], ...] | None:
    """Parse a TF-style version directory name (``0.2``, ``0.2pre``, ``1.7.3``).

    Returns a sort key mirroring Text-Fabric's own ordering: components
    compare numerically, and a pre-release suffix sorts *before* the bare
    release it precedes (``0.2pre`` < ``0.2`` < ``0.2.1``). ``None`` when the
    name is not a version at all.
    """
    components: list[tuple[int, int, str]] = []
    for part in name.split("."):
        match = _VERSION_COMPONENT.match(part)
        if match is None:
            return None
        suffix = match.group(2) or ""
        components.append((int(match.group(1)), 0 if suffix else 1, suffix))
    return tuple(components)


def _find_dataset_root(
    files: dict[PurePosixPath, ZipInfo],
) -> tuple[PurePosixPath, list[str]]:
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
    if len(candidates) == 1:
        return candidates[0], []

    # Text-Fabric's standard layout keeps versions as sibling directories
    # (`0.1/`, `0.2/`, `0.2pre/`); its own tooling loads the latest. Mirror
    # that here instead of rejecting every real-world versioned export
    # (issue #184); the hard error below stays for genuinely ambiguous
    # archives (unrelated roots, e.g. two different corpora in one zip).
    versions = {path: _parse_tf_version(path.name) for path in candidates}
    parents = {path.parent for path in candidates}
    if len(parents) == 1 and all(key is not None for key in versions.values()):
        selected = max(candidates, key=lambda path: versions[path] or ())
        others = ", ".join(
            path.name
            for path in sorted(candidates, key=lambda path: versions[path] or ())
            if path != selected
        )
        return selected, [
            f"Selected dataset version {selected.name} (also found: {others})"
        ]

    roots = ", ".join(str(path) for path in sorted(candidates, key=str))
    raise ValueError(f"ZIP contains multiple Text-Fabric datasets: {roots}")


def convert_tf_zip_to_tf(
    source: str,
    output_dir: str | Path,
    *,
    category: CorpusCategory | None = None,
) -> ConvertedDataset:
    """Extract the Text-Fabric dataset in ``source`` to ``output_dir``.

    A ZIP using Text-Fabric's standard versioned layout (sibling version
    directories like ``0.1/``, ``0.2/``, ``0.2pre/``) imports its latest
    version, with the choice recorded on ``ConvertedDataset.warnings`` so it
    surfaces in the conversion log (issue #184).

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
            dataset_root, warnings = _find_dataset_root(files)
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

    return ConvertedDataset.wrap(output_dir, category=category, warnings=warnings)
