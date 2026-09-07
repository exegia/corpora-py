---
name: tf-reference-id
description: >-
  Parse, resolve, create and normalize schema-agnostic reference identifiers
  for Text-Fabric corpora — strings like `bhsa@2021/Deut:4:2!clause1`,
  `mobydick/Moby-Dick:3!word12` or `urn:tf:kjv:Gen:1:1` — turning them into
  TF nodes and turning nodes back into stable, shareable references. Use this
  skill whenever someone wants to cite, link, bookmark, address, or look up a
  passage, verse, chapter, paragraph, clause, phrase or word in any
  Text-Fabric / Context-Fabric corpus (Biblical or secular), asks "what is the
  identifier/URI/URN for this node", "which node is Deut 4:2 clause 1", wants
  to build reference links into an app or dataset, mentions OSIS-style refs,
  T.nodeFromSection, L.d, sectionFromNode, or needs a citation scheme that
  works across book/chapter/verse AND volume/chapter/paragraph corpora. Also
  use it when a reference "doesn't resolve", indices look off by one, or a
  clause "belongs to two verses" — the bundled script encodes the boundary
  and versioning rules that make those cases deterministic.
---

# Text-Fabric reference identifiers

One grammar for every TF corpus, resolved against whatever section hierarchy
the corpus itself declares in `otext.tf`:

```
[corpus[@version]/]<Sec1>[:<Sec2>[:...]][!<otype><i>[-<j>]]
urn:tf:<corpus>[@version]:<Sec1>[:<Sec2>...][!<otype><i>[-<j>]]
```

| Reference | Means |
|---|---|
| `bhsa@2021/Deut:4:2` | the verse node for Deuteronomy 4:2 in BHSA version 2021 |
| `bhsa/Deut:4:2!clause1` | 1st clause anchored in that verse (latest loaded version) |
| `kjv/Deut:4:2!word3-5` | words 3–5 of the verse, as a list |
| `mobydick/Moby-Dick:3!word12` | 12th word of chapter 3 |
| `iliad/Book1:Line5!word4` | works the same for `book:line` corpora |
| `Moby-Dick%3A Or, The Whale:1:2` | a book title containing `:` — percent-encode reserved chars |

The section path is whatever `T.sectionTypes` says — `book:chapter:verse`,
`volume:chapter:para`, `act:scene:line`. Nothing is hardcoded. The `!` selector
picks any node type by 1-based position *within that section*.

Everything below is implemented in `scripts/tfref.py`. Use the script rather
than re-deriving the logic: the two design decisions that make references
deterministic (anchoring and versioning) are easy to get subtly wrong by hand.

---

## Two decisions you need to know about

**Anchor-to-first-slot.** Clauses, sentences and phrases routinely straddle
verse or paragraph boundaries. A node is addressed from the innermost section
that contains its *first* slot, and only from there. So a clause running from
verse 2 into verse 3 is `…:2!clauseN`, never `…:3!clause…`, and verse 3's
clause count does not include it. `resolve` and `serialize` both use this rule,
which is what makes `serialize(resolve(r)) == normalize(r)` hold. Plain
`L.d(verse, otype='clause')` does not give you this — it may include or omit the
spanning clause depending on the loader — so the script builds the child list
itself from slot positions.

**Version is optional in, explicit out.** `bhsa/Deut:4:2!clause1` means "against
whatever BHSA is loaded". When you *produce* a reference, the script writes the
dataset's `@version` (read from `otype.tf` metadata) whenever one exists, so a
reference someone stores today still means the same thing after the corpus is
rebuilt and clause numbering shifts. Positional indices are only stable within
(corpus, version, language) — say so when handing references to people who will
persist them. If a reference pins a version that differs from the loaded corpus,
resolve refuses rather than guessing.

Details, EBNF and the escaping rule: `references/grammar.md`.

---

## Using it

### From the command line (no text-fabric install needed)

```bash
python scripts/tfref.py info      CORPUS_DIR                      # levels, types, version
python scripts/tfref.py parse     'bhsa@2021/Deut:4:2!clause1'    # grammar check → JSON
python scripts/tfref.py resolve   CORPUS_DIR 'Deut:4:2!clause1'   # → {"nodes":[...]}
python scripts/tfref.py serialize CORPUS_DIR 427553 --corpus bhsa # node → reference
python scripts/tfref.py serialize CORPUS_DIR 1 4 --corpus bhsa    # range → …!word1-4
python scripts/tfref.py normalize CORPUS_DIR 'bhsa/Deut:4:2!clause1' [--urn]
```

`CORPUS_DIR` is the directory that holds `otype.tf` (unzip first; it is often
nested as `tf/` or `tf/2021/`). The stdlib loader reads only `otype`,
`oslots`, `otext` and the section features, so it is quick even for BHSA.

### From Python, with a live TF session

```python
import sys; sys.path.insert(0, "scripts")
import tfref
from tf.app import use
A = use("etcbc/bhsa", silent="deep")          # or Fabric(...).loadAll()
api = A.api

node  = tfref.resolve("bhsa/Deut:4:2!clause1", api)
nodes = tfref.resolve("bhsa/Deut:4:2!word1-3", api)      # list
ref   = tfref.serialize(node, api, corpus_id="bhsa")     # 'bhsa@2021/Deut:4:2!clause1'
urn   = tfref.serialize(node, api, corpus_id="bhsa", form="urn")
canon = tfref.normalize("bhsa/Deut:4:2!clause1", api)   # version filled in
```

Pass `lang="en"` (or whatever `T.sectionFromNode` accepts) when the corpus has
multilingual headings; references are bound to the heading language they were
written in. `resolve_ref(ref, api)` and `node_to_ref(node, api, corpus_id)` are
kept as thin wrappers for code written against the original design note.

### Errors are specific on purpose

`ParseError` (bad grammar, shows the offending piece), `SectionNotFound`
(unknown heading, too many levels, version mismatch, corpus has no
`@sectionTypes`), `TypeNotInSection` (no such otype, or none anchored in that
section), `IndexOutOfRange` (tells you how many there are). Relay the message —
it already says what to fix.

---

## Working with the corpus, not just the string

- **Validate before you address.** If `resolve` says a section does not exist or
  the corpus has no section types, the corpus is usually the problem, not the
  reference. Run `text-fabric-validator` (`tf_validate.py`) first; missing
  `oslots` entries and gaps in section numbering are exactly the faults that
  make references silently point nowhere.
- **Gaps are handled by falling outward.** A node whose first slot is in no
  innermost section (front matter before chapter 1, a chapter the walker
  dropped) is addressed from the next level up: `mobydick/Moby-Dick!word3`.
  That is legal and round-trips, but it is a smell — mention it and point at
  the validator's `TF0xx` report.
- **Heading strings must match the corpus exactly**, including language and
  punctuation. `info` prints the section features; when in doubt, `serialize` a
  known node and copy the heading it produces.
- **Choosing the level to cite.** Prefer the innermost section plus a selector
  (`Deut:4:2!clause1`) over a chapter-level index (`Deut:4!clause17`): the
  former survives edits elsewhere in the chapter, the latter does not.
- **Ranges** are inclusive, same otype, same anchor section. For spans that
  cross sections, emit two references (start and end) — the grammar
  deliberately does not encode multi-section spans.

---

## Verifying

```bash
python scripts/test_tfref.py
```

Runs ~45 checks against `assets/fixtures/spanning-mini` — three section levels,
a book title containing `:` and spaces, a clause and a phrase that each straddle
a paragraph boundary, and a sentence that straddles a chapter — through the
stdlib loader and, when `text-fabric` is importable, through the real TF api as
well. Run it if references behave unexpectedly before blaming the corpus.
