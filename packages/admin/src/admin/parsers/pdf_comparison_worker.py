"""Offline independent visual OCR. This worker never receives converted text."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import tempfile
from pathlib import Path

LOCK_PATH = Path(__file__).with_name("pdf_comparison.lock.json")


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def check_runtime(models, binary):
    lock = json.loads(LOCK_PATH.read_text())
    for package, version in lock["packages"].items():
        if importlib.metadata.version(package) != version:
            raise ValueError(f"Independent PDF comparison requires {package}=={version}")
    for record in [*lock["models"]["files"], dict(lock["binary"], file=str(binary))]:
        path = models / record["file"]
        if path.stat().st_size != record["bytes"] or digest(path.read_bytes()) != "sha256:" + record["sha256"]:
            raise ValueError("Independent PDF comparison model or binary checksum mismatch")
    return lock


def save_checkpoint(path, snapshot):
    payload = {"snapshot": snapshot, "snapshot_sha256": digest(encoded(snapshot))}
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(encoded(payload))
        temporary = Path(handle.name)
    temporary.replace(path)


def run(source, output, models, binary):
    lock = check_runtime(models, binary)
    os.environ.update(
        HF_HUB_OFFLINE="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
        SURYA_GGUF_LOCAL_MODEL_PATH=str(models / "surya-2.gguf"),
        SURYA_GGUF_LOCAL_MMPROJ_PATH=str(models / "surya-2-mmproj.gguf"),
        LLAMA_CPP_BINARY=str(binary), SURYA_INFERENCE_BACKEND="llamacpp",
        SURYA_INFERENCE_PARALLEL="1", SURYA_MAX_TOKENS_FULL_PAGE=str(lock["max_tokens"]),
        SURYA_INFERENCE_TIMEOUT_SECONDS="300", SURYA_INFERENCE_STARTUP_TIMEOUT="120",
        SURYA_INFERENCE_KEEP_ALIVE="false", DISABLE_TQDM="true",
    )
    import pypdfium2 as pdfium
    from bs4 import BeautifulSoup
    from surya.inference import SuryaInferenceManager
    from surya.recognition import RecognitionPredictor

    source_hash = digest(source.read_bytes())
    pdf = pdfium.PdfDocument(source)
    snapshot = {
        "profile": lock["profile"], "source_sha256": source_hash,
        "lock_sha256": digest(LOCK_PATH.read_bytes()), "page_count": len(pdf),
        "models": lock["models"], "packages": lock["packages"], "pages": {},
        "render_dpi": lock["render_dpi"], "max_tokens": lock["max_tokens"],
    }
    if output.is_file():
        existing = json.loads(output.read_text())
        previous = existing["snapshot"]
        if existing["snapshot_sha256"] != digest(encoded(previous)):
            raise ValueError("Independent PDF comparison checkpoint checksum mismatch")
        if any(previous[key] != snapshot[key] for key in snapshot if key != "pages"):
            raise ValueError("Independent PDF comparison checkpoint revision mismatch")
        snapshot = previous
    manager = SuryaInferenceManager(method="llamacpp")
    try:
        manager.start()
        predictor = RecognitionPredictor(manager)
        original_generate = manager.generate
        calls = []

        def checked_generate(batch):
            results = original_generate(batch)
            for request, result in zip(batch, results, strict=True):
                if result.error or result.token_count >= (request.max_tokens or lock["max_tokens"]):
                    raise ValueError("Independent visual OCR was truncated or failed; no partial comparison accepted")
                calls.append({"raw": result.raw, "token_count": result.token_count})
            return results

        manager.generate = checked_generate
        for index in range(len(pdf)):
            page_id = str(index + 1)
            if page_id not in snapshot["pages"]:
                page = pdf[index]
                bitmap = page.render(scale=lock["render_dpi"] / 72)
                image = bitmap.to_pil().convert("RGB")
                calls.clear()
                pixels_hash = digest(image.tobytes())
                result = predictor([image], full_page=True)[0]
                if any(block.error for block in result.blocks):
                    raise ValueError(f"Independent visual OCR failed on page {page_id}; retry resumes its checkpoint")
                blocks = sorted(result.blocks, key=lambda block: block.reading_order)
                text = "\n".join(
                    BeautifulSoup(block.html, "html.parser").get_text(separator=" ")
                    for block in blocks if not block.skipped
                )
                snapshot["pages"][page_id] = {
                    "text": text, "blocks": [b.model_dump(mode="json") for b in blocks], "raw_calls": list(calls),
                    "pixels_sha256": pixels_hash, "dimensions": list(image.size),
                }
                image.close()
                bitmap.close()
                page.close()
                save_checkpoint(output, snapshot)
            print("CORPORA_COMPARISON_PROGRESS " + json.dumps({"completed": index + 1, "total": len(pdf)}), flush=True)
        if digest(source.read_bytes()) != source_hash:
            raise ValueError("Original PDF changed during independent visual OCR")
    finally:
        manager.stop()
        pdf.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.output, args.models, args.binary)
