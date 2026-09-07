#!/usr/bin/env python3
"""Self-test for tfref.py against the bundled spanning-mini fixture.

Runs with plain `python3 scripts/test_tfref.py` (no pytest needed). If
text-fabric is importable, the same checks are repeated through the real
TF api so the two backends are proven to agree.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tfref  # noqa: E402

FIXTURE = os.path.join(HERE, "..", "assets", "fixtures", "spanning-mini")
BOOK = "Moby-Dick: Or, The Whale"
BOOK_ENC = "Moby-Dick%3A Or, The Whale"
PREFIX = f"mobydick@0.1/{BOOK_ENC}"

FAILS = []


def check(name, got, want):
    ok = got == want
    print(
        ("  ok   " if ok else "  FAIL ")
        + name
        + ("" if ok else f"\n         got  {got!r}\n         want {want!r}")
    )
    if not ok:
        FAILS.append(name)


def expect_error(name, exc, fn):
    try:
        fn()
    except exc:
        print("  ok   " + name)
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL {name}: raised {type(e).__name__}: {e}")
        FAILS.append(name)
    else:
        print(f"  FAIL {name}: no error raised")
        FAILS.append(name)


def run(corpus, label):
    print(f"[{label}]")
    R = lambda ref: tfref.resolve(ref, corpus)  # noqa: E731,N806
    S = lambda n, **kw: tfref.serialize(n, corpus, corpus_id="mobydick", **kw)  # noqa: E731,N806

    # --- parsing -----------------------------------------------------------
    r = tfref.parse(f"{PREFIX}:1:2!clause1")
    check("parse decodes %3A and keeps spaces", r.sections, (BOOK, "1", "2"))
    check("parse corpus/version", (r.corpus, r.version), ("mobydick", "0.1"))
    check("parse selector", (r.target_type, r.start, r.end), ("clause", 1, 1))
    check("short form round-trips", tfref.parse(r.short()), r)
    check("urn round-trips", tfref.from_urn(r.urn()), r)
    check(
        "urn encodes spaces",
        r.urn(),
        "urn:tf:mobydick@0.1:Moby-Dick%3A%20Or,%20The%20Whale:1:2!clause1",
    )
    expect_error("parse rejects 0 index", tfref.ParseError, lambda: tfref.parse("x/A:1!word0"))
    expect_error(
        "parse rejects inverted range", tfref.ParseError, lambda: tfref.parse("x/A:1!word5-2")
    )
    expect_error("parse rejects empty section", tfref.ParseError, lambda: tfref.parse("x/A::1"))

    # --- sections ----------------------------------------------------------
    check("book node", R(f"{BOOK_ENC}"), 28)
    check("chapter node (int-typed feature)", R(f"{BOOK_ENC}:2"), 27)
    check("para node", R(f"{BOOK_ENC}:1:2"), 24)
    check("version omitted resolves", R(f"mobydick/{BOOK_ENC}:1:1"), 23)
    expect_error(
        "wrong version pinned", tfref.VersionMismatch, lambda: R(f"mobydick@9/{BOOK_ENC}:1")
    )
    expect_error("unknown section", tfref.SectionNotFound, lambda: R(f"{BOOK_ENC}:7"))
    expect_error("too deep", tfref.SectionNotFound, lambda: R(f"{BOOK_ENC}:1:1:1"))

    # --- sub-units and the boundary policy --------------------------------
    check("word in para", R(f"{BOOK_ENC}:1:1!word3"), 3)
    check("word range", R(f"{BOOK_ENC}:1:1!word1-4"), [1, 2, 3, 4])
    check("spanning clause anchors to first-slot para", R(f"{BOOK_ENC}:1:2!clause1"), 16)
    check("next para does not re-count the spanner", R(f"{BOOK_ENC}:2:1!clause1"), 17)
    expect_error(
        "next para has only one clause", tfref.IndexOutOfRange, lambda: R(f"{BOOK_ENC}:2:1!clause2")
    )
    check("chapter-level clause index", R(f"{BOOK_ENC}:1!clause2"), 16)
    check("spanning phrase", R(f"{BOOK_ENC}:1:2!phrase2"), 21)
    check("sentence spanning chapters, from chapter 1", R(f"{BOOK_ENC}:1!sentence2"), 14)
    expect_error(
        "sentence not anchored in chapter 2",
        tfref.TypeNotInSection,
        lambda: R(f"{BOOK_ENC}:2!sentence1"),
    )
    expect_error("unknown otype", tfref.TypeNotInSection, lambda: R(f"{BOOK_ENC}:1!verse1"))

    # --- serialize ---------------------------------------------------------
    check("serialize section node", S(24), f"{PREFIX}:1:2")
    check("serialize book node", S(28), f"mobydick@0.1/{BOOK_ENC}")
    check("serialize spanning clause", S(16), f"{PREFIX}:1:2!clause1")
    check("serialize clause after spanner", S(17), f"{PREFIX}:2:1!clause1")
    check("serialize word", S(10), f"{PREFIX}:2:1!word2")
    check("serialize range", S([1, 4]), f"{PREFIX}:1:1!word1-4")
    check(
        "serialize urn",
        S(16, form="urn"),
        "urn:tf:mobydick@0.1:Moby-Dick%3A%20Or,%20The%20Whale:1:2!clause1",
    )
    expect_error("range across anchors rejected", tfref.TypeNotInSection, lambda: S([16, 17]))

    # --- normalize / round trip -------------------------------------------
    check(
        "normalize fills version",
        tfref.normalize(f"mobydick/{BOOK_ENC}:1:2!clause1", corpus),
        f"{PREFIX}:1:2!clause1",
    )
    check(
        "normalize is idempotent",
        tfref.normalize(f"{PREFIX}:1!clause2", corpus),
        f"{PREFIX}:1:2!clause1",
    )
    for ref in [
        f"{PREFIX}:1:1!word2",
        f"{PREFIX}:1:2!phrase2",
        f"{PREFIX}:2",
        f"{PREFIX}:1:1!word2-3",
    ]:
        n = R(ref)
        back = S([n[0], n[-1]] if isinstance(n, list) else n)
        check(f"round trip {ref}", back, ref)

    # --- compat wrappers ---------------------------------------------------
    check("resolve_ref wrapper", tfref.resolve_ref(f"{BOOK_ENC}:1:1!word1", corpus), 1)
    check(
        "node_to_ref wrapper",
        tfref.node_to_ref(1, corpus),
        f"@0.1/{BOOK_ENC}:1:1!word1".replace("@0.1/", ""),
    )


def main():
    run(tfref.load_corpus(FIXTURE), "stdlib loader")
    try:
        from tf.fabric import Fabric  # type: ignore
    except ImportError:
        print("[text-fabric not installed — api backend skipped]")
    else:
        tmp = tempfile.mkdtemp()
        dst = os.path.join(tmp, "spanning-mini")
        shutil.copytree(FIXTURE, dst)
        api = Fabric(locations=dst, silent="deep").loadAll(silent="deep")
        run(tfref.load_corpus(api), "text-fabric api")
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed: {FAILS}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
