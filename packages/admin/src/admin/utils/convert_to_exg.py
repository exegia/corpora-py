"""
Convert a Text-Fabric dataset directory to the Exegia corpus format (.exg).

File layout produced:
    {name}.exg          ← final deliverable (zip)
    └── .git            ← git repository for future version and diff features of the text.
    └── manifest.json   ← corpus metadata
    └── index.json      ← corpus list of files
    └── corpus.exgc     ← the original .tf dataset (zip)
"""

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


# ── TF header parser ──────────────────────────────────────────────────────────


def _parse_tf_header(path: Path) -> dict[str, str]:
    """Return the @key=value pairs from a Text-Fabric file header.

    Header ends at the first blank line. Lines without '=' are stored with
    an empty-string value (e.g. '@node' → {'node': ''}).
    """
    meta: dict[str, str] = {}
    try:
        with path.open(encoding="utf-8") as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                if not line:
                    break
                if not line.startswith("@"):
                    continue
                key_val = line[1:]
                if "=" in key_val:
                    k, _, v = key_val.partition("=")
                    meta[k.strip()] = v.strip()
                else:
                    meta[key_val.strip()] = ""
    except Exception as exc:
        logger.warning("Could not parse header of %s: %s", path, exc)
    return meta


def _collect_node_types(otype_path: Path) -> list[str]:
    """Return the unique node types listed in otype.tf (data section)."""
    types: list[str] = []
    seen: set[str] = set()
    in_data = False
    try:
        with otype_path.open(encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not in_data:
                    if line == "":
                        in_data = True
                    continue
                if not line or line.startswith("#"):
                    continue
                # data lines: "1-426584\tword"  or just "word"
                parts = line.split("\t")
                node_type = parts[-1].strip()
                if node_type and node_type not in seen:
                    seen.add(node_type)
                    types.append(node_type)
    except Exception as exc:
        logger.warning("Could not parse node types from %s: %s", otype_path, exc)
    return types


# ── Manifest builder ──────────────────────────────────────────────────────────


def _build_manifest(dataset_dir: Path) -> dict:
    otext = dataset_dir / "otext.tf"
    otype = dataset_dir / "otype.tf"

    otext_meta = _parse_tf_header(otext) if otext.exists() else {}
    otype_meta = _parse_tf_header(otype) if otype.exists() else {}

    tf_files = list(dataset_dir.rglob("*.tf"))
    total_size = sum(f.stat().st_size for f in dataset_dir.rglob("*") if f.is_file())

    section_types = [
        s.strip() for s in otext_meta.get("sectionTypes", "").split(",") if s.strip()
    ]
    section_features = [
        s.strip() for s in otext_meta.get("sectionFeatures", "").split(",") if s.strip()
    ]

    text_formats = {
        k[len("fmt:") :]: v for k, v in otext_meta.items() if k.startswith("fmt:")
    }

    return {
        "format": "exg",
        "format_version": "1.0",
        "name": otext_meta.get("name") or dataset_dir.name,
        "version": otext_meta.get("version") or otype_meta.get("version") or "",
        "description": otext_meta.get("description")
        or otype_meta.get("description")
        or "",
        "written_by": otext_meta.get("writtenBy") or otype_meta.get("writtenBy") or "",
        "date_written": otext_meta.get("dateWritten")
        or otype_meta.get("dateWritten")
        or "",
        "section_types": section_types,
        "section_features": section_features,
        "text_formats": text_formats,
        "node_types": _collect_node_types(otype),
        "source_folder": dataset_dir.name,
        "tf_file_count": len(tf_files),
        "total_size_bytes": total_size,
    }


# ── Index builder ────────────────────────────────────────────────────────────


def _build_index(dataset_dir: Path) -> list[dict]:
    """Return a list of file entries for all .tf files in the dataset."""
    return [
        {"path": str(f.relative_to(dataset_dir)), "size_bytes": f.stat().st_size}
        for f in sorted(dataset_dir.rglob("*.tf"))
    ]


# ── Packaging ─────────────────────────────────────────────────────────────────


def convert_to_exg(dataset_dir: Path, destination: Path) -> Path:
    """Package a Text-Fabric dataset directory as an .exg file.

    Steps:
      1. Parse otext.tf / otype.tf → manifest.json
      2. List .tf files             → index.json
      3. Initialise empty repo      → .git
      4. Zip the dataset directory  → corpus.exgc
      5. Bundle all                 → {dataset_dir.name}.exg

    Args:
        dataset_dir:  Path to folder containing .tf files (must have otext.tf + otype.tf).
        destination:  Directory where the final .exg file will be saved.

    Returns:
        Path to the produced .exg file.

    Raises:
        FileNotFoundError: if dataset_dir does not exist.
        ValueError: if otext.tf or otype.tf are missing.
    """
    dataset_dir = dataset_dir.resolve()
    if not dataset_dir.is_dir():
        raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")
    if (
        not (dataset_dir / "otext.tf").exists()
        or not (dataset_dir / "otype.tf").exists()
    ):
        raise ValueError(f"otext.tf and otype.tf are required in {dataset_dir}")

    destination.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as _tmp:
        staging = Path(_tmp) / dataset_dir.name
        staging.mkdir()

        # Step 1 — manifest
        manifest = _build_manifest(dataset_dir)
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.debug("Manifest written: %s", manifest_path)

        # Step 2 — index.json
        index = _build_index(dataset_dir)
        index_path = staging / "index.json"
        index_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.debug("Index written: %s", index_path)

        # Step 3 — .git (empty repository for future versioning)
        subprocess.run(
            ["git", "init", str(staging)],
            check=True,
            capture_output=True,
        )
        logger.debug(".git initialised in %s", staging)

        # Step 4 — corpus.exgc (zip of the .tf dataset)
        exgc_base = staging / "corpus"
        shutil.make_archive(
            str(exgc_base),
            "zip",
            root_dir=dataset_dir.parent,
            base_dir=dataset_dir.name,
        )
        (staging / "corpus.zip").rename(staging / "corpus.exgc")
        logger.debug("corpus.exgc created in %s", staging)

        # Step 5 — {name}.exg (zip of staging folder)
        exg_name = dataset_dir.name
        exg_base = destination / exg_name
        shutil.make_archive(
            str(exg_base), "zip", root_dir=staging.parent, base_dir=staging.name
        )
        exg_path = destination / f"{exg_name}.zip"
        final_path = destination / f"{exg_name}.exg"
        exg_path.rename(final_path)

    logger.info("Produced %s", final_path)
    return final_path
