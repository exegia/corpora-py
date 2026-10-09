---
title: End-to-end local linking walkthrough
description: Runnable extraction, automatic/manual linking, review, snapshot and withdrawal fixture.
tags: [references, examples, integration]
---

# Run and inspect

From the repository root:

```bash
uv run python packages/linking/examples/end_to_end.py --output /tmp/reference-linking-demo
```

The selected output directory must be new or empty. The example uses the
umbrella's existing BeautifulSoup dependency, writes only local artifacts, and
performs no network, distribution, account or live database operation. Its source
HTML, scripture text, work catalog and numbering context are synthetic fixtures,
not a claim about a real Bible edition or scholarly citation authority.

# Connected workflows

1. Extract the actual HTML fixture with strict UTF-8 and pinned byte/text digests.
   The citation crosses inline markup, and the text includes astral Unicode.
2. Register an automatic conversion event and retain original DOM/text mappings.
   Retrieve the native mapping selections against the pinned HTML asset.
3. Create a manual link from the selected full sentence to the fixture passage.
   Both records use the same Reference values, SnapshotResolver and working store.
4. Resolve the automatic citation through an explicit numbering-context mapping,
   validate the exact target quote/context, then review both records. Separate
   converter, reader and reviewer actors appear in working history.
5. Export both approved references at their exact working versions, leaving working
   publication draft. Import the snapshot into a second local store as pending
   drafts, with repeat-import decisions unchanged.
6. Record local fixture acknowledgments; retry the original conversion and confirm
   IDs/current publication state remain unchanged. Withdraw the automatic reference
   and prepare the next snapshot containing only the manual reference.
7. Retrieve the exact target selection from the verified immutable text snapshot.

# Artifacts and scope

The output directory contains the source HTML, converted stream, original
conversion-event report, approved snapshot, next snapshot after withdrawal,
working/publication history, summary and both local SQLite stores. Snapshot IDs
match the original automatic/manual reference IDs; prior citation requests and
approval evidence remain in history. Imported records require fresh review.

The publication flags in this example record trusted **local fixture assertions**;
no remote artifact was distributed or removed. The target is a text selection,
so its lossless metadata is exported in JSON rather than fabricating a C-USX
anchor. Full C-USX insertion and multi-destination delivery remain separate work.
The example orchestrates existing adapters without changing production TF jobs.

The integration test inspects stored actions, original mapping evidence, target
agreement across workflows, exported versions, import state and withdrawal
omission. Core and format adapter tests cover ambiguous/unavailable/stale outcomes;
this walkthrough chooses a fully verifiable happy path.
