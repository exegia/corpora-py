"""Runnable local HTML → references → review → snapshot → withdrawal example.

Requires corpora-py/BeautifulSoup. Biblical content and numbering are synthetic
fixtures, not a real edition or versification authority. No external I/O occurs.
"""

import argparse
import json
from pathlib import Path
from uuid import UUID, uuid4

from corpora_linking import (
    BibleBook,
    BibleCitationDetector,
    CatalogEntry,
    CitationLocator,
    Endpoint,
    PassageEntry,
    Provenance,
    Reference,
    SnapshotCatalog,
    SnapshotResolver,
    TextLocator,
    TextSnapshot,
)

from corpora_py.linking_events import ConversionEventRegistry
from corpora_py.linking_html import extract_html_references_input, retrieve_html_selection
from corpora_py.linking_ledger import PublicationLedger
from corpora_py.linking_pdf import sha256_revision
from corpora_py.linking_publication import PublicationSnapshot, SnapshotPublicationAdapter
from corpora_py.linking_store import SQLiteReferenceStore


def _required(store: SQLiteReferenceStore, reference_id: UUID) -> Reference:
    reference = store.get(reference_id)
    if reference is None:
        raise ValueError("example reference missing from working store")
    return reference


def run_example(output_dir: Path) -> dict:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("example output directory must be empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    data = Path(__file__).with_name("fixtures").joinpath("study.html").read_bytes()
    # The fixture's declared extraction stream includes preserved trailing HTML LF.
    expected_text = "😀 Compare John 3:16.\n\n"
    original = Endpoint(
        work_id="fixture:essay",
        edition_id="fixture:edition",
        package_id="fixture:html",
        revision=sha256_revision(data),
        document_id="study",
    )
    converted = Endpoint(
        work_id=original.work_id,
        edition_id=original.edition_id,
        package_id="fixture:converted",
        revision=sha256_revision(expected_text.encode()),
        document_id="study",
    )
    conversion = extract_html_references_input(
        data, original=original, converted=converted, asset_id="study.html"
    )
    detector = BibleCitationDetector(
        books=(BibleBook(work_id="fixture:john", aliases=("John",)),),
        stream_id="body",
        profile="fixture:bible",
        scheme_id="fixture:numbering",
        scheme_version="1",
        agent_id="fixture:converter",
    )
    worker = SQLiteReferenceStore(output_dir / "working.db", actor_id="fixture:converter")
    registry = ConversionEventRegistry(worker, authority_id="fixture:working")
    event_id = uuid4()
    event = registry.register(
        conversion,
        detector,
        event_id=event_id,
        detector_revision="fixture:detector/v1",
        reason="initial conversion",
    )
    auto = event.report.references[0].reference
    for mapping in event.report.references[0].mappings:
        mapped_text = mapping.converted.locators[0]
        assert isinstance(mapped_text, TextLocator)
        assert retrieve_html_selection(data, mapping.original) == mapped_text.exact

    verse_text = "Before. Fixture verse text. After."
    verse_base = Endpoint(
        work_id="fixture:john",
        edition_id="fixture:edition",
        package_id="fixture:bible",
        revision=sha256_revision(verse_text.encode()),
        document_id="john",
    )
    quote = "Fixture verse text."
    target = Endpoint.model_validate(
        {
            **verse_base.model_dump(),
            "locators": [
                TextLocator(
                    stream_id="body",
                    start=8,
                    end=8 + len(quote),
                    exact=quote,
                    prefix="Before. ",
                    suffix=" After.",
                )
            ],
        }
    )
    sentence = "😀 Compare John 3:16."
    manual_source = Endpoint.model_validate(
        {
            **converted.model_dump(),
            "locators": [
                TextLocator(
                    stream_id="body", start=0, end=len(sentence), exact=sentence, suffix="\n\n"
                )
            ],
        }
    )
    manual = Reference(
        source=manual_source,
        target=target,
        relationship="core:related",
        provenance=Provenance(origin="manual", agent_id="fixture:reader", method="selection"),
    )
    reader = SQLiteReferenceStore(worker.path, actor_id="fixture:reader")
    reader.save(manual, expected_version=None, reason="selected sentence and target passage")
    citation = auto.target.locators[0]
    assert isinstance(citation, CitationLocator)
    resolver = SnapshotResolver(
        catalog=SnapshotCatalog(
            entries=(
                CatalogEntry(work_id="fixture:essay", names=("Essay",)),
                CatalogEntry(work_id="fixture:john", names=("John",)),
            )
        ),
        passages=(PassageEntry(citation=citation, target=target),),
        snapshots=(
            conversion.converted,
            TextSnapshot(endpoint=verse_base, stream_id="body", text=verse_text),
        ),
    )
    reviewer = SQLiteReferenceStore(worker.path, actor_id="fixture:reviewer")
    for reference in (auto, manual):
        reviewer.resolve_target(
            reference.id, expected_version=1, resolver=resolver, reason="verified target selection"
        )
        reviewer.approve(
            reference.id, expected_version=2, resolver=resolver, reason="reviewed source and target"
        )
    ids = (auto.id, manual.id)
    adapter = SnapshotPublicationAdapter("fixture:working")
    payload = adapter.export_working(reviewer, ids)
    assert all(_required(reviewer, reference_id).publication == "draft" for reference_id in ids)
    imported = SQLiteReferenceStore(output_dir / "imported.db", actor_id="fixture:importer")
    for decision in adapter.plan_import(payload, imported):
        adapter.apply_import(decision, imported, reason="import for independent review")
    assert all(
        decision.outcome == "unchanged" for decision in adapter.plan_import(payload, imported)
    )
    assert all(_required(imported, reference_id).review == "pending" for reference_id in ids)

    operator = SQLiteReferenceStore(worker.path, actor_id="fixture:operator")
    ledger = PublicationLedger(operator, authority_id="fixture:working")
    for reference_id in ids:
        ledger.acknowledge_snapshot(
            payload,
            reference_id,
            event_id=uuid4(),
            expected_version=3,
            reason="local fixture acknowledgment; no distribution",
        )
    retry = registry.register(
        conversion,
        detector,
        event_id=event_id,
        detector_revision="fixture:detector/v1",
        reason="conversion retry",
    )
    assert retry == event and _required(worker, auto.id).publication == "published"
    ledger.withdraw(
        auto.id, event_id=uuid4(), expected_version=4, reason="withdraw automatic fixture link"
    )
    next_payload = ledger.export_current(ids)
    next_snapshot = PublicationSnapshot.model_validate_json(next_payload)
    assert tuple(entry.reference.id for entry in next_snapshot.entries) == (manual.id,)
    assert all(
        entry.reference.target == target
        for entry in PublicationSnapshot.model_validate_json(payload).entries
    )
    verified_target = resolver.resolve(target)
    assert verified_target.status == "resolved" and verified_target.candidates == (target,)
    target_locator = verified_target.candidates[0].locators[0]
    assert isinstance(target_locator, TextLocator)
    retrieved_target = verse_text[target_locator.start : target_locator.end]
    assert retrieved_target == quote
    summary = {
        "automatic_id": str(auto.id),
        "manual_id": str(manual.id),
        "conversion_event_id": str(event_id),
        "retrieved_target": retrieved_target,
        "exported_count": 2,
        "next_export_count": 1,
        "automatic_state": _required(worker, auto.id).publication,
        "manual_state": _required(worker, manual.id).publication,
        "imported_review": "pending",
        "retry_preserved_ids": retry == event,
    }
    (output_dir / "study.html").write_bytes(data)
    (output_dir / "converted.txt").write_text(conversion.converted.text, encoding="utf-8")
    (output_dir / "conversion-event.json").write_text(
        event.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / "approved-snapshot.json").write_bytes(payload)
    (output_dir / "after-withdrawal.json").write_bytes(next_payload)
    (output_dir / "working-history.json").write_text(
        json.dumps(
            [
                revision.model_dump(mode="json")
                for reference_id in ids
                for revision in worker.history(reference_id)
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output_dir / "publication-history.json").write_text(
        json.dumps(
            [
                item.model_dump(mode="json")
                for reference_id in ids
                for item in ledger.history(reference_id)
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="new or empty local output directory"
    )
    print(json.dumps(run_example(parser.parse_args().output), ensure_ascii=False, indent=2))
