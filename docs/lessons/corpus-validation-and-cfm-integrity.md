---
title: Corpus validation & .cfm integrity checking
description: How validate_corpus works, the .corpus archive shipped-cache check, and the cfabric gotchas learned restoring it (issue #30).
tags: [validation, context-fabric, cfm, mcp, lessons-learned]
---

# Corpus validation & `.cfm` integrity checking

Knowledge captured while restoring and extending the `validate_corpus` capability
(GitHub issue #30, branch `feature/corpus-validation`). Covers what the validator
checks, the `.corpus` archive mode that verifies the *shipped* Context-Fabric
cache, and the non-obvious cfabric behaviour that shapes the implementation.

## What validation actually proves

A Text-Fabric dataset is "valid" when it survives the full Context-Fabric cycle
and both loading paths agree. The logic lives in
[validate.py](../../packages/mcp/src/corpora_mcp/validate.py) and is exposed two
ways: the `validate_corpus` MCP tool in
[server.py](../../packages/mcp/src/corpora_mcp/server.py) and the `POST /validate`
endpoint in [validation_api.py](../../src/corpora_py/validation_api.py) (wired
into the combined app in [app.py](../../src/corpora_py/app.py)).

The cycle is: load the `.tf` source with text-fabric; load with cfabric (which
auto-compiles the `.cfm` cache); reload with cfabric from the `.cfm` mmap. It
then compares `max_slot`, `max_node`, `node_types`, `node_features`,
`edge_features` plus sampled node/edge/text feature values across those paths.
Any mismatch becomes a human-readable entry in `reasons[]`.

## Two modes — directory vs `.corpus` archive

The entry point is chosen by whether the target is a directory or a file.

| Mode | Input | What it checks | Shipped `.cfm`? |
| --- | --- | --- | --- |
| `validate_corpus` | a `.tf` **directory** | clears any cache, **recompiles**, round-trips | No — recompiled from scratch |
| `validate_corpus_archive` | a `.corpus` **zip file** | loads the shipped `corpora/.cfm/` **as-is**, then compares it against a `.tf` recompile | **Yes** |

The `.corpus` archive (produced by
[convert_to_corpus.py](../../packages/admin/src/admin/converters/convert_to_corpus.py))
packs the dataset under `corpora/` with a **nested** compiled cache at
`corpora/.cfm/<n>/`, plus `manifest.yml` / `toc.yml`. Archive mode unzips to a
temp dir, locates the payload (`corpora/`, falling back to any dir holding
`otype.tf`), and derives the corpus name from `manifest.yml`.

> **Gotcha — order matters.** `validate_corpus` starts by deleting `.cfm` and
> `.tf` caches so a recompile attributes errors cleanly. That means the shipped
> cache must be loaded **before** `clear_caches()` runs. `validate_shipped_cfm=True`
> captures the shipped-cache stats first, then proceeds with the normal recompile.
> A `.tf`-directory validation therefore *cannot* detect a corrupt shipped
> cache — only archive mode does.

## cfabric behaviours worth knowing

- **The mmap signal is a private attribute.** The only reliable way to tell
  "reloaded from the `.cfm` mmap cache" apart from "recompiled from `.tf`" is
  `Fabric._loaded_from_cfm`. Checking that a `.cfm/` directory merely *exists*
  is not sufficient — the first load creates it. On a fresh load the attribute
  is absent (falsy); on the mmap reload it is `True`.
- **`cfabric.__version__` lies.** The module string reports `0.5.0` while the
  installed distribution is `0.5.7` (matches the `context-fabric>=0.5.7` pin in
  the root [pyproject.toml](../../pyproject.toml)). Verify the *distribution*
  version (`uv pip show context-fabric`), not `cfabric.__version__`.
- **Lazy imports keep the split intact.** `corpora-mcp` deliberately does not
  hard-depend on the Context-Fabric runtime; `validate.py` imports `cfabric` /
  `tf` inside the load helpers so importing the module never requires them.

## Design decisions

- **Validation logic lives in `corpora_mcp`, the endpoint in `corpora_py`.**
  Putting the HTTP route in `admin` would force an `admin -> corpora-mcp`
  dependency and collapse the slim-client/heavy-admin split (see
  [CLAUDE.md](../../CLAUDE.md)). The umbrella package already depends on both,
  so the router belongs there.
- **Invalid corpus is a result, not an error.** The endpoint returns `200` with
  `{ valid: false, reasons: [...] }` when a dataset loads but fails validation;
  only an unresolvable target (missing path / unknown corpus) is a `404`. The
  MCP tool instead raises `ToolError` on invalid, per its original contract.
- **Auth is automatic.** `/validate` is gated by `AuthMiddleware` simply by
  being mounted on the combined app; validation is stateless, so there is no
  per-resource ownership to enforce (unlike `/convert` jobs).

## Testing lessons

- **Mock at the definition site.** The tool/endpoint do a lazy
  `from ...validate import validate_corpus` *inside* the function, so tests patch
  `corpora_mcp.validate.validate_corpus` (where it is defined), not a
  server-module attribute.
- **Real fixtures beat elaborate fakes.** `context-fabric` is a declared dep, so
  a 5-file mini-corpus exercises the true `.tf` to `.cfm` to mmap cycle, and a
  real `.corpus` zip (compile the `.cfm`, corrupt one cache file for the negative
  case) proves the shipped-cache check end-to-end — far more faithful than
  hand-building a fake `Fabric` API.
- Tests: [test_validate.py](../../tests/mcp/test_validate.py) and
  [test_validation_api.py](../../tests/corpora_py/test_validation_api.py).

## Scope note

Issue #30 was validation-only; the lost `download_corpus` /
`fetch_datasets_from_git` helpers were intentionally **not** restored.
