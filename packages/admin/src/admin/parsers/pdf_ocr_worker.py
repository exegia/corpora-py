"""Pinned, offline Docling worker; executable with an isolated OCR Python runtime.

The standalone file intentionally imports no admin modules: the API runtime can
remain lightweight while the configured worker has the heavy OCR dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from itertools import groupby
from pathlib import Path

LOCK_PATH = Path(__file__).with_name("pdf_ocr.lock.json")


def page_bounded_merges(predict, elements):
    """Keep Docling's merge prediction within each contiguous page group."""
    result = {}
    for _page, group in groupby(elements, key=lambda element: element.page_no):
        result.update(predict(sorted_elements=list(group)))
    return result


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def prepare_models(root: Path) -> dict:
    """Explicitly download locked public assets; conversion itself stays offline."""
    import urllib.request

    from huggingface_hub import snapshot_download

    lock = json.loads(LOCK_PATH.read_text())
    root.mkdir(parents=True, exist_ok=True)
    for model in lock["models"]:
        snapshot_download(
            repo_id=model["repo"],
            revision=model["revision"],
            allow_patterns=[file["path"] for file in model["files"]],
            local_dir=root / model["repo"].replace("/", "--"),
        )
    tessdata = root / "tessdata"
    tessdata.mkdir(exist_ok=True)
    for file in lock["tessdata"]["files"]:
        path = tessdata / file["file"]
        if path.is_file() and digest(path) == "sha256:" + file["sha256"]:
            continue
        url = (
            "https://raw.githubusercontent.com/"
            + lock["tessdata"]["repo"]
            + "/"
            + lock["tessdata"]["revision"]
            + "/"
            + file["file"]
        )
        temporary = path.with_suffix(".download")
        try:
            with (
                urllib.request.urlopen(url, timeout=60) as response,
                temporary.open("wb") as stream,
            ):
                while chunk := response.read(1024 * 1024):
                    stream.write(chunk)
            if digest(temporary) != "sha256:" + file["sha256"]:
                raise ValueError("Downloaded PDF OCR language data failed its locked checksum")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return check_runtime(root)


def check_runtime(root: Path) -> dict:
    lock = json.loads(LOCK_PATH.read_text())
    packages = {}
    for name, expected in lock["packages"].items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ValueError(f"Pinned PDF OCR runtime is missing {name}=={expected}") from exc
        if actual != expected:
            raise ValueError(f"PDF OCR requires {name}=={expected}; found {actual}")
        packages[name] = actual
    checked = []
    for model in lock["models"]:
        folder = root / model["repo"].replace("/", "--")
        for file in model["files"]:
            path = folder / file["path"]
            if not path.is_file() or path.stat().st_size != file["bytes"]:
                raise ValueError(
                    "Pinned PDF OCR model files are unavailable; prepare the locked assets"
                )
            if digest(path) != "sha256:" + file["sha256"]:
                raise ValueError("PDF OCR model checksum mismatch; restore the locked snapshot")
        checked.append(model)
    for file in lock["tessdata"]["files"]:
        path = root / "tessdata" / file["file"]
        if not path.is_file() or digest(path) != "sha256:" + file["sha256"]:
            raise ValueError("PDF OCR language-data checksum mismatch; restore the locked OCR data")
    return {
        "profile": lock["profile"],
        "lock_sha256": digest(LOCK_PATH),
        "packages": packages,
        "models": checked,
        "tessdata": lock["tessdata"],
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def convert(source: Path, output: Path, root: Path, languages: list[str], device: str) -> None:
    provenance = check_runtime(root)
    source_hash = digest(source)
    os.environ.update(
        HF_HUB_OFFLINE="1",
        HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
        TOKENIZERS_PARALLELISM="false",
        PYTORCH_ENABLE_MPS_FALLBACK="1",
    )
    import tesserocr
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        LayoutOptions,
        OcrMode,
        PdfPipelineOptions,
        TableFormerMode,
        TesseractOcrOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline
    from pypdfium2 import PdfDocument

    with PdfDocument(source) as pdf:
        page_count = len(pdf)

    class ProgressPdfPipeline(StandardPdfPipeline):
        def __init__(self, pipeline_options):
            super().__init__(pipeline_options)
            self.completed_pages = set()
            predictor = self.reading_order_model.ro_model
            original_predict = predictor.predict_merges
            predictor.predict_merges = lambda sorted_elements: page_bounded_merges(
                original_predict, sorted_elements
            )

        def _release_page_resources(self, item):
            # Private hook verified against the locked Docling version: called
            # by the final page assembly stage, including for failed items.
            super()._release_page_resources(item)
            if not item.is_failed and item.payload is not None:
                self.completed_pages.add(item.page_no)
                print(
                    "CORPORA_PDF_PROGRESS "
                    + json.dumps({"completed": len(self.completed_pages), "total": page_count}),
                    flush=True,
                )

    allowed = {"eng", "heb", "grc"}
    if not languages or set(languages) - allowed:
        raise ValueError("Pinned PDF OCR supports eng, heb and grc language data")
    layout = LayoutOptions()
    layout.model_spec = layout.model_spec.model_copy(
        update={
            "repo_id": "docling-project/docling-layout-heron",
            "revision": "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8",
        }
    )
    options = PdfPipelineOptions(
        artifacts_path=root,
        do_ocr=True,
        do_table_structure=True,
        enable_remote_services=False,
        allow_external_plugins=False,
    )
    options.layout_options = layout
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    options.ocr_options = TesseractOcrOptions(
        mode=OcrMode.FULL_PAGE,
        lang=languages,
        path=str(root / "tessdata"),
    )
    options.accelerator_options = AcceleratorOptions(device=device, num_threads=4)
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_cls=ProgressPdfPipeline, pipeline_options=options
            ),
        }
    )
    print("CORPORA_PDF_PROGRESS " + json.dumps({"completed": 0, "total": page_count}), flush=True)
    result = converter.convert(source, raises_on_error=True)
    if str(result.status) != "ConversionStatus.SUCCESS" or result.errors:
        raise ValueError("Forced PDF OCR did not complete; no partial conversion accepted")
    if digest(source) != source_hash:
        raise ValueError("PDF source changed during OCR; restart with the original file")
    document = result.document
    payload = document.export_to_dict()
    blocks = []
    for item, _level in document.iterate_items(with_groups=False):
        label = str(item.label.value)
        if label == "table":
            # Keep every table row, including headers, in the projected stream.
            data = item.data
            rows = [["" for _ in range(data.num_cols)] for _ in range(data.num_rows)]
            for cell in data.table_cells:
                rows[cell.start_row_offset_idx][cell.start_col_offset_idx] = cell.text
            text = "\n".join("\t".join(row) for row in rows)
        else:
            text = getattr(item, "text", "")
        blocks.append(
            {
                "label": label,
                "text": text,
                "prov": [p.model_dump(mode="json") for p in item.prov],
                "self_ref": item.self_ref,
            }
        )
    snapshot = {"document": payload, "blocks": blocks}
    encoded = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    provenance.update(
        source_sha256=source_hash,
        snapshot_sha256="sha256:" + hashlib.sha256(encoded).hexdigest(),
        options={
            "ocr_mode": "full_page",
            "languages": languages,
            "table_mode": "accurate",
            "device": device,
            "threads": 4,
            "remote_services": False,
            "cross_page_text_merges": False,
        },
        tesseract=tesserocr.tesseract_version(),
    )
    output.write_text(
        json.dumps(
            {"snapshot": snapshot, "provenance": provenance}, ensure_ascii=False, sort_keys=True
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--languages", default="eng,heb,grc")
    parser.add_argument("--device", choices=["auto", "cpu", "mps", "cuda"], default="auto")
    args = parser.parse_args()
    try:
        if args.prepare:
            print(json.dumps(prepare_models(args.models)))
        elif args.check:
            print(json.dumps(check_runtime(args.models)))
        else:
            if args.source is None or args.output is None:
                parser.error("--source and --output are required for conversion")
            convert(args.source, args.output, args.models, args.languages.split(","), args.device)
    except (ValueError, ImportError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
