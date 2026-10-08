---
title: Reference linking core
description: Isolated linking values and adapter ports for Corpora and future extraction.
tags: [references, python]
---

# Reference linking core

`corpora-linking` (import `corpora_linking`) is an MIT-licensed uv workspace
package with Pydantic as its only runtime dependency. It contains validated
source/target values, typed selection locators, provenance, independent
resolution/review/publication state, conversion mappings, JSON round trips,
conservative text-anchor verification and adapter protocols. It performs no I/O.
Its version is independent of Corpora releases; it is bundled in `corpora-py`
and is not added to the repository's automatic PyPI publishing workflow.

```python
from corpora_linking import Endpoint, Provenance, Reference, TextLocator

source = Endpoint(
    work_id="urn:example:work", edition_id="urn:example:edition",
    package_id="study", revision="1", document_id="chapter",
    locators=(TextLocator(stream_id="body", start=0, end=4, exact="John"),),
)
reference = Reference(
    source=source, target=Endpoint(work_id="urn:example:commentary"),
    provenance=Provenance(origin="manual", agent_id="reader", method="selection"),
)
assert Reference.model_validate_json(reference.model_dump_json()) == reference
```

A work-only target intentionally has no fabricated passage. A `resolved` result
may verify a whole work; it does not automatically imply a passage locator.
Fields are immutable; changes use a new validated instance via
`Reference.model_validate({...reference.model_dump(), "review": "approved"})`.
Pydantic's unchecked `model_copy(update=...)` and `model_construct` are not
validation APIs. Adapter code must validate untrusted records at every boundary.

Build: `uv build --package corpora-linking --wheel --out-dir dist/`.
Tests: `uv run pytest tests/linking`. See the
[implementation specification](../../specs/reference-linking/spec.md) and
[agent instructions](AGENTS.md) for constraints and staged work.

## Bible detection

`BibleCitationDetector` implements `Detector` using caller-supplied `BibleBook`
work IDs and aliases, a stream ID, and explicit profile/scheme/version context.
Call `detect(source, text)` on the complete immutable stream and a fully scoped
source endpoint without locators. It recognizes explicit `John 3:16` and
same-chapter ranges such as `Jn. 3:16–18`, preserving spelling, scalar offsets
and context. It does not infer implicit books, validate verse existence, resolve
editions, or accept compound lists/cross-chapter ranges. Every output is unresolved
and pending review. Colliding aliases emit one hypothesis per catalog work with
ambiguity evidence; consumers must retain all hypotheses together for review.
Reruns allocate new IDs: persistence adapters must implement the documented
reconciliation policy before repeated conversion is integrated.

Run the [manual retrieval example](examples/manual_link.py):
`uv run python packages/linking/examples/manual_link.py`.
It verifies both selections and rejects changed revisions or quote/context mismatches.
