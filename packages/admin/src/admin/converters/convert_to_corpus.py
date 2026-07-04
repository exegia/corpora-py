"""Package a Text-Fabric dataset (.tf + compiled .cfm cache) into a `.corpus` zip archive.

The archive contains:
- manifest.yml (ICorpusManifest)
- toc.yml (ICorpusToc)
- assets/ (optional cover/thumbnail/images)
- corpora/ (the dataset payload: *.tf files + .cfm/ cache)
- .git/ (a snapshot repo for the payload, for version history)

See packages/admin/README.md for an overview of the conversion/packaging pipeline.
"""

import shutil
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from cfabric import Fabric

from .convert_to_cfm import convert_to_cfm


def _file_entry(path: Path, *, kind: str, visible: bool = True) -> dict[str, Any]:
    """Build an `IFile` entry for `path`."""
    return {
        "id": str(uuid.uuid4()),
        "path": path.name,
        "type": kind,
        "name": path.stem,
        "visible": visible,
    }


def _copy_asset(assets_dir: Path, asset: str | Path) -> dict[str, Any]:
    asset = Path(asset)
    assets_dir.mkdir(exist_ok=True)
    dest = assets_dir / asset.name
    shutil.copy2(asset, dest)
    return _file_entry(dest, kind="image")


def _build_manifest(
    *,
    uid: str,
    name: str,
    description: str,
    version: str,
    language: str,
    language_code: str,
    corpus_type: str,
    category: str,
    written_date: str,
    dataset_id: str,
    project_id: str,
    assets: list[dict[str, Any]],
    thumbnail: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build an `ICorpusManifest`."""
    return {
        "uid": uid,
        "name": name,
        "description": description,
        "version": version,
        "language": language,
        "languageCode": language_code,
        "type": corpus_type,
        "format": "corpus",
        "format_version": "1",
        "category": category,
        "written_date": written_date,
        "tocFile": "toc.yml",
        "datasetId": dataset_id,
        "projectId": project_id,
        "assets": assets,
        "thumbnail": thumbnail,
    }


def _build_toc(
    *,
    uid: str,
    version: str,
    corpus_id: str,
    corpora_dir: Path,
    publisher_id: str,
    author_ids: list[str] | str,
) -> dict[str, Any]:
    """Build an `ICorpusToc` by introspecting the compiled corpus."""
    result = Fabric(locations=str(corpora_dir)).loadAll()

    has_nodes = False
    has_features = False
    has_sections = False
    if not isinstance(result, bool):
        # `F`/`T` are dynamically populated at load time, so cfabric's type
        # stubs don't know their attributes (`otype`, `sectionTypes`, ...).
        has_nodes = len(result.F.otype.all) > 0  # type: ignore[attr-defined]
        has_features = len(result.Fall()) > 2  # more than otype/oslots
        has_sections = bool(result.T.sectionTypes)  # type: ignore[attr-defined]

    files = [_file_entry(p, kind="text") for p in sorted(corpora_dir.rglob("*")) if p.is_file()]
    total_size = sum(p.stat().st_size for p in corpora_dir.rglob("*") if p.is_file())

    return {
        "uid": uid,
        "version": version,
        "corpusId": corpus_id,
        "has_sections": has_sections,
        "has_features": has_features,
        "has_nodes": has_nodes,
        "files": files,
        "total_file_count": len(files),
        "total_file_size": total_size,
        "publisherId": publisher_id,
        "authorId": author_ids,
    }


def _git_snapshot(root: Path) -> None:
    """Init a git repo at the archive root and commit the payload, so the
    `.corpus` archive carries its own version history (see Schema.md)."""
    run = lambda *args: subprocess.run(args, cwd=root, check=True, capture_output=True)  # noqa: E731
    run("git", "init", "-q")
    run("git", "add", "-A")
    run(
        "git",
        "-c",
        "user.name=Corpora",
        "-c",
        "user.email=corpora@exegia.co",
        "commit",
        "-q",
        "-m",
        "Initial corpus payload",
    )


def convert_to_corpus(
    tf_dir: str | Path,
    output_path: str | Path,
    *,
    name: str,
    description: str = "",
    version: str = "1.0.0",
    language: str = "",
    language_code: str = "",
    corpus_type: str = "",
    category: str = "",
    written_date: str = "",
    dataset_id: str = "",
    project_id: str = "",
    publisher_id: str = "",
    author_ids: list[str] | str = "",
    assets: list[str | Path] | None = None,
    thumbnail: str | Path | None = None,
) -> Path:
    """
    Package a Text-Fabric dataset at `tf_dir` into a `.corpus` archive at
    `output_path`.

    `tf_dir` must already contain the `.tf` files produced by one of the
    `_{format}_to_tf.py` converters. `dataset_id`/`project_id`/`publisher_id`/
    `author_ids` are assigned by the caller (the Corpora/Exegia backend) —
    this function has no way to know them on its own.
    """
    tf_dir = Path(tf_dir)
    output_path = Path(output_path)
    convert_to_cfm(tf_dir)  # ensure corpora/.cfm/ exists before packaging

    manifest_uid = str(uuid.uuid4())

    with tempfile.TemporaryDirectory(prefix="corpus-") as tmp:
        root = Path(tmp)
        corpora_dir = root / "corpora"
        shutil.copytree(tf_dir, corpora_dir)

        assets_dir = root / "assets"
        assets_dir.mkdir()  # always present per the canonical structure, even if empty
        asset_entries = [_copy_asset(assets_dir, asset) for asset in assets or []]
        thumbnail_entry = _copy_asset(assets_dir, thumbnail) if thumbnail else None

        manifest = _build_manifest(
            uid=manifest_uid,
            name=name,
            description=description,
            version=version,
            language=language,
            language_code=language_code,
            corpus_type=corpus_type,
            category=category,
            written_date=written_date or datetime.now(UTC).isoformat(),
            dataset_id=dataset_id,
            project_id=project_id,
            assets=asset_entries,
            thumbnail=thumbnail_entry,
        )
        (root / "manifest.yml").write_text(yaml.safe_dump(manifest, sort_keys=False))

        toc = _build_toc(
            uid=str(uuid.uuid4()),
            version=version,
            corpus_id=manifest_uid,
            corpora_dir=corpora_dir,
            publisher_id=publisher_id,
            author_ids=author_ids,
        )
        (root / "toc.yml").write_text(yaml.safe_dump(toc, sort_keys=False))

        _git_snapshot(root)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        archive = shutil.make_archive(str(output_path.with_suffix("")), "zip", root_dir=root)
        Path(archive).rename(output_path)

    return output_path
