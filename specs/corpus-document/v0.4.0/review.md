# Review and implementation boundary

This draft is concrete enough to review and validate offline. It does not change
runtime models, source conversion behavior, Supabase tables or application APIs.
The [real-source report](experiments/report.md) distinguishes source extraction
quality from normalized graph validity. Core point positions now cover empty PDF
pages and TEI/USX milestones. Existing parser whitespace and EPUB-order findings
are documented; runtime fixes and OCR remain separate work.

1. Review identity authority and namespace registration before publication. URNs
   avoid route/citation identity coupling; deployment still needs an allocation
   authority and cross-bundle collision enforcement.
2. Review profile feature schemas and locator semantics. The current schema
   validates namespaced shape and required capabilities, not arbitrary feature
   value semantics or physical coordinates.
3. Review XML ergonomics. The implemented typed encoding preserves JSON values,
   text controls and extension keys, but is not TEI or USX and has no XSD. The
   [USX assessment](usx-adapter.md) covers a draft source projection, not a parser.
4. Implement adapters separately with source-specific slot/offset maps and honest
   conversion reports. The fixtures are synthetic conformance examples, not
   evidence of real-source losslessness, complete numbering inventories or a
   production reference parser.
5. Distribute a reviewed, exact-version bundle to the six listed projects. Fill
   the manifest template with commit and SHA-256 pins; add consumer binding tests
   and CI hash checks. Other projects were not inspected or modified in this task.

## Verification commands

```sh
uv run --no-project --with jsonschema python specs/corpus-document/v0.4.0/conformance_tests.py
uv run --no-project --with jsonschema --with ruff ruff check scripts/check_corpus_document.py specs/corpus-document/v0.4.0
uv run --no-project --with jsonschema python scripts/check_corpus_document.py --bundle dist/corpus-document/0.4.0
```

The bundle destination must be new or empty. Generated bundles are disposable,
verified copies, not independently editable contract sources. The manifest covers
all portable files, including the checker; hash the manifest itself to obtain a
consumer pin. Import the bundle into a temporary consumer and rerun its tests
before adopting it. Hash verification does not establish source-asset integrity:
that requires fetching assets and checking their bytes during import.
