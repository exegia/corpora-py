"""GraphQL root — Query type and schema assembly."""

from __future__ import annotations

from typing import Optional

import strawberry

from .corpus import registry
from .references import parse_reference
from .types import (
    Book,
    Chapter,
    Corpus,
    SearchMatch,
    Verse,
    Word,
    WordFilter,
    _book_from_node,
    _chapter_from_node,
    _corpus_from_handle,
    _text_of,
    _verse_from_node,
    _word_from_node,
)


def _find_book_node(corpus, book_name: str) -> int | None:
    target = book_name.strip().lower()
    for node in corpus.F.otype.s("book"):
        name = corpus.feature("book", node)
        if name and name.lower() == target:
            return node
    return None


@strawberry.type
class Query:
    @strawberry.field(description="List every corpus currently loaded into the registry.")
    def corpora(self) -> list[Corpus]:
        return [_corpus_from_handle(h) for h in registry.all()]

    @strawberry.field(description="Fetch a single corpus by its registered name.")
    def corpus(self, name: str) -> Optional[Corpus]:
        handle = registry.get(name)
        return None if handle is None else _corpus_from_handle(handle)

    @strawberry.field(description="Fetch a book by name within a given corpus.")
    def book(self, corpus: str, name: str) -> Optional[Book]:
        handle = registry.get(corpus)
        if handle is None:
            return None
        node = _find_book_node(handle, name)
        return None if node is None else _book_from_node(handle, node)

    @strawberry.field(description='Fetch a chapter by reference, e.g. "Genesis 1".')
    def chapter(self, corpus: str, reference: str) -> Optional[Chapter]:
        handle = registry.get(corpus)
        if handle is None:
            return None
        parsed = parse_reference(reference)
        node = handle.T.nodeFromSection((parsed.book, parsed.chapter))
        return None if node is None else _chapter_from_node(handle, node)

    @strawberry.field(description='Fetch a single verse by reference, e.g. "Genesis 1:1".')
    def verse(self, corpus: str, reference: str) -> Optional[Verse]:
        handle = registry.get(corpus)
        if handle is None:
            return None
        parsed = parse_reference(reference)
        if parsed.verse is None:
            return None
        node = handle.T.nodeFromSection((parsed.book, parsed.chapter, parsed.verse))
        return None if node is None else _verse_from_node(handle, node)

    @strawberry.field(
        description='Fetch every verse covered by a reference. Accepts "Gen 1", "Gen 1:1", or "Gen 1:1-5".'
    )
    def passage(self, corpus: str, reference: str) -> list[Verse]:
        handle = registry.get(corpus)
        if handle is None:
            return []
        parsed = parse_reference(reference)

        if parsed.verse is None:
            chapter_node = handle.T.nodeFromSection((parsed.book, parsed.chapter))
            if chapter_node is None:
                return []
            verse_nodes = handle.L.d(chapter_node, otype="verse") or []
            return [_verse_from_node(handle, n) for n in verse_nodes]

        start = parsed.verse
        end = parsed.verse_end if parsed.verse_end is not None else parsed.verse
        verses = []
        for v in range(start, end + 1):
            node = handle.T.nodeFromSection((parsed.book, parsed.chapter, v))
            if node is not None:
                verses.append(_verse_from_node(handle, node))
        return verses

    @strawberry.field(
        description=(
            "Find words matching a structured filter. Each field maps to one "
            "dimension of a TF/CF search — lexical (lemma, gloss), morphological "
            "(partOfSpeech, verbStem, verbTense, gender, number, person), and "
            "section (book, chapter, verse) — so callers don't need to know the "
            "raw pattern syntax. Fields are AND-combined; omit any you don't care "
            "about."
        )
    )
    def words(
        self,
        corpus: str,
        filter: Optional[WordFilter] = None,
        limit: int = 100,
    ) -> list[Word]:
        handle = registry.get(corpus)
        if handle is None:
            return []
        limit = max(1, min(limit, 1000))
        filt = filter or WordFilter()
        gloss_needle = filt.gloss.lower() if filt.gloss else None

        scope_node: int | None = None
        if filt.book is not None:
            section: tuple = (filt.book,)
            if filt.chapter is not None:
                section = (filt.book, filt.chapter)
                if filt.verse is not None:
                    section = (filt.book, filt.chapter, filt.verse)
            scope_node = handle.T.nodeFromSection(section)
            if scope_node is None:
                return []
        elif filt.chapter is not None or filt.verse is not None:
            # chapter/verse without a book don't uniquely identify a section.
            return []

        nodes = (
            handle.L.d(scope_node, otype="word")
            if scope_node is not None
            else handle.F.otype.s("word")
        )

        results: list[Word] = []
        for node in nodes:
            word = _word_from_node(handle, node)
            if filt.lemma and word.lemma != filt.lemma:
                continue
            if filt.part_of_speech and word.part_of_speech != filt.part_of_speech:
                continue
            if filt.verb_stem and word.verb_stem != filt.verb_stem:
                continue
            if filt.verb_tense and word.verb_tense != filt.verb_tense:
                continue
            if filt.gender and word.gender != filt.gender:
                continue
            if filt.number and word.number != filt.number:
                continue
            if filt.person and word.person != filt.person:
                continue
            if gloss_needle and (not word.gloss or gloss_needle not in word.gloss.lower()):
                continue
            results.append(word)
            if len(results) >= limit:
                break
        return results

    @strawberry.field(
        description=(
            "Run a raw Text-Fabric / Context-Fabric search query. "
            "See https://context-fabric.ai/docs/core for the pattern syntax."
        )
    )
    def search(self, corpus: str, pattern: str, limit: int = 100) -> list[SearchMatch]:
        handle = registry.get(corpus)
        if handle is None:
            return []
        limit = max(1, min(limit, 1000))

        raw = handle.S.search(pattern)
        if raw is None:
            return []
        matches: list[SearchMatch] = []
        for row in raw:
            if len(matches) >= limit:
                break
            nodes = list(row) if isinstance(row, (tuple, list)) else [row]
            if not nodes:
                continue
            first = nodes[0]
            verse_ancestors = handle.L.u(first, otype="verse") or []
            reference = None
            if verse_ancestors:
                verse = _verse_from_node(handle, verse_ancestors[0])
                reference = verse.reference
            text = " · ".join(filter(None, (_text_of(handle, n) for n in nodes)))
            matches.append(SearchMatch(reference=reference, text=text))
        return matches


schema = strawberry.Schema(query=Query)
