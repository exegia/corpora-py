# Reference grammar, escaping and semantics

## EBNF

```
reference   = short | urn ;
short       = [ corpus-part "/" ] section-path [ selector ] ;
urn         = "urn:tf:" corpus-part ":" section-path [ selector ] ;

corpus-part = corpus-id [ "@" version ] ;
corpus-id   = 1*( ALPHA / DIGIT / "_" / "." / "-" ) ;
version     = 1*( ALPHA / DIGIT / "_" / "." / "-" ) ;

section-path = section-value *( ":" section-value ) ;
section-value = 1*( unreserved / pct-encoded ) ;   ; see Escaping
selector    = "!" otype index [ "-" index ] ;
otype       = ( ALPHA / "_" ) *( ALPHA / DIGIT / "_" ) ;
index       = 1*DIGIT ;                             ; 1-based, > 0
```

- Depth of `section-path` ≤ `len(T.sectionTypes)`. Fewer components address a
  higher-level section (`Deut:4` is the chapter node).
- A selector with `-j` is an inclusive range; `j ≥ i`; both refer to the same
  otype inside the same section.
- A `short` reference without `corpus-part` is corpus-relative; it cannot be
  turned into a URN until a corpus id is supplied.

## Escaping (one rule, both directions)

Inside a `section-value`, percent-encode these five characters and nothing
else is required: `%`, `:`, `/`, `!`, `@`.

- Short form leaves spaces and everything else literal:
  `Song of songs:1:1`, `Moby-Dick%3A Or, The Whale:1`.
- URN form additionally encodes space as `%20` so it is a valid URI:
  `urn:tf:mobydick:Moby-Dick%3A%20Or,%20The%20Whale:1`.
- Decoding is plain `urllib.parse.unquote` in both forms, so a value encoded
  more aggressively (e.g. `Song%20of%20songs`) still parses; `normalize`
  re-emits the canonical minimal encoding.

Section values are typed by the corpus, not by their spelling: `Deut:4:2` and
`Deut:04:2` are the same reference in a corpus whose `chapter` feature is
`int`, and a book literally named `1` stays a string in a corpus whose `book`
feature is `str`. `Adapter.typed_sections` does the cast from the feature's
`@valueType`.

## Semantics

### Section resolution
`T.nodeFromSection(typed_tuple, lang=…)` (or the equivalent lookup table when
reading `.tf` files directly). Partial tuples give higher-level nodes.

### Sub-unit resolution — anchor-to-first-slot
For section node `S` with slot range `[lo, hi]` and otype `t`:

```
children(S, t) = sorted( { n : otype(n) = t  and  lo ≤ firstSlot(n) ≤ hi },
                         key = (firstSlot(n), -lastSlot(n), n) )
```

`!t<i>` is `children(S, t)[i-1]`. The sort key is TF's canonical order (earlier
start first; among equal starts, the larger node first).

Why "first slot lies inside" rather than "fully embedded": every node then has
exactly one address, the index sequence inside a section has no holes, and a
node that spills over the boundary is still findable from the section where a
reader would look for it (where it starts). `L.d` cannot be relied on for this:
TF and Context-Fabric differ on whether they include partially overlapping
nodes.

### Serialization
For a section node: its heading tuple truncated to its own level.
For any other node: `anchor = innermost section containing firstSlot(node)`;
if the innermost level has a gap there, walk outward until some section
contains it; then `index = children(anchor, otype(node)).index(node)+1`.

### Version
- Input: `@version` optional. Absent ⇒ resolve against the loaded corpus.
  Present and ≠ loaded corpus's version ⇒ `SectionNotFound` (refuse to guess).
- Output: always emit the loaded corpus's version when it declares one
  (`@version` in `otype.tf` metadata; `api.TF.features['otype'].metaData`).
  A corpus with no declared version produces version-less references — flag
  this to the user, because those references are not durable across rebuilds.

### Language
`lang` is passed straight through to `T.nodeFromSection` / `T.sectionFromNode`.
A reference is bound to the heading language it was written in; there is no
language tag in the grammar by design (put it in the corpus id if you need to
distinguish, e.g. `bhsa-en`).

### Multi-section spans
Not expressible in one reference. Emit a pair `(start_ref, end_ref)` and let
the consumer walk slots from `firstSlot(resolve(start))` to
`lastSlot(resolve(end))`. Extending the grammar with `..` between two full
references would be backwards compatible if it is ever needed.

## Worked examples on the bundled fixture

`assets/fixtures/spanning-mini`: `book > chapter > para`, slots 1–12.

```
para  (1,1) = slots 1–4     (1,2) = 5–8     (2,1) = 9–12
clause 15 = 1–4   16 = 5–10 (spans para 1:2 → 2:1)   17 = 11–12
sentence 13 = 1–4  14 = 5–12 (spans chapter 1 → 2)
```

| Reference | Node | Why |
|---|---|---|
| `…:1:2!clause1` | 16 | first slot 5 is in para (1,2) |
| `…:2:1!clause1` | 17 | node 16 is *not* re-counted here |
| `…:2:1!clause2` | IndexOutOfRange | para (2,1) anchors one clause |
| `…:1!clause2` | 16 | chapter-level index: clauses 15, 16 start in ch. 1 |
| `…:2!sentence1` | TypeNotInSection | sentence 14 starts in chapter 1 |
| `serialize(16)` | `…@0.1/…:1:2!clause1` | anchor of slot 5, version from otype.tf |
