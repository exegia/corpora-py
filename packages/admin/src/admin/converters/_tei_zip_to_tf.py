"""
TEI ZIP to Text-Fabric Converter

Converts a ZIP archive of TEI (or TEI-in-plain-`.xml`) documents into a
single Text-Fabric dataset: each member document is parsed with the same
`TeiParser` the single-file `tei` converter uses, and all of them are walked
into one dataset via `convert_documents` -- one "text" root node per member
document, carrying that document's `<teiHeader>` metadata as features.
Members convert in archive-path order (sorted), so a corpus zipped as
`01-genesis.xml`, `02-exodus.xml`, ... keeps its intended sequence.

Node Types / Features: identical to `_tei_to_tf.py` (same parser, same
`otype_for`) -- the only difference is that the dataset can contain several
"text" roots instead of exactly one.

Archive safety mirrors `_tf_zip_to_tf.py`: path traversal, symlinks,
encrypted members, member count, and expanded size are all validated before
any bytes are written. macOS `__MACOSX/` resource forks and hidden dotfiles
are ignored.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile, ZipInfo

from ..parsers import TeiParser
from ..parsers.schema import Document
from ._tei_to_tf import _otype_for
from ._tf_zip_to_tf import _MAX_FILES, _MAX_UNCOMPRESSED_BYTES, _safe_path
from ._walker import convert_documents

_TEI_SUFFIXES = frozenset({".tei", ".xml"})


def _is_noise(path: PurePosixPath) -> bool:
    """Housekeeping entries that say nothing about the corpus itself."""
    return path.parts[0] == "__MACOSX" or path.name.startswith(".")


def _tei_members(archive: ZipFile) -> list[ZipInfo]:
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if len(infos) > _MAX_FILES:
        raise ValueError(f"TEI ZIP contains more than {_MAX_FILES:,} files")
    if sum(info.file_size for info in infos) > _MAX_UNCOMPRESSED_BYTES:
        raise ValueError("Expanded TEI ZIP exceeds the 2 GiB limit")

    members = [
        info
        for info in infos
        for path in (_safe_path(info),)
        if not _is_noise(path) and path.suffix.lower() in _TEI_SUFFIXES
    ]
    if not members:
        raise ValueError(
            "ZIP does not contain any TEI documents (.tei or .xml files are required)"
        )
    return sorted(members, key=lambda info: info.filename)


def convert_tei_zip_to_tf(source: str, output_dir: str | Path) -> Path:
    """Convert every TEI/XML document inside ``source`` into one Text-Fabric
    dataset at ``output_dir``."""
    parser = TeiParser()
    documents: list[Document] = []

    try:
        with (
            ZipFile(source) as archive,
            tempfile.TemporaryDirectory(prefix="tei-zip-") as scratch,
        ):
            for info in _tei_members(archive):
                # Flattened to the basename: members were validated against
                # traversal above, and the parser only needs a readable file.
                extracted = Path(scratch) / f"{len(documents)}-{PurePosixPath(info.filename).name}"
                with (
                    archive.open(info) as member,
                    extracted.open("wb") as out,
                ):
                    shutil.copyfileobj(member, out)
                documents.append(parser.parse(str(extracted)))
    except BadZipFile as exc:
        raise ValueError("Uploaded file is not a valid ZIP archive") from exc

    return convert_documents(
        documents,
        output_dir,
        root_type="text",
        otype_for=_otype_for,
        format_value=parser.format.value,
        source_label=source,
    )
