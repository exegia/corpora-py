"""GraphQL types — user-friendly surface over the Context-Fabric node graph.

Design notes:
- Internal TF node IDs and corpus names are marked `strawberry.Private` so they
  never leak into the public schema.
- Every type carries a back-reference (`_corpus`, `_node`) so nested resolvers
  can walk the graph lazily without the caller threading state.
- Field names use natural language (`lemma`, `partOfSpeech`, `gloss`) instead
  of BHSA shorthand (`lex`, `sp`). A generic `feature(name)` escape hatch lets
  power users reach raw features when needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import strawberry

from .corpus import CorpusHandle, registry
from .references import format_reference

if TYPE_CHECKING:
    pass


# ── Feature mapping ──────────────────────────────────────────────────────────
# User-facing names → the raw TF/CF feature that holds the value. The resolver
# walks this map so corpora that use slightly different feature names can
# still be surfaced by extending the list.

_WORD_TEXT_FEATURES = ("g_word_utf8", "g_word", "text")
_LEMMA_FEATURES = ("voc_lex_utf8", "lex_utf8", "lex", "lemma")
_GLOSS_FEATURES = ("gloss", "gloss_en")
_PART_OF_SPEECH = ("sp", "pos")
_GENDER = ("gn", "gender")
_NUMBER = ("nu", "number")
_PERSON = ("ps", "person")
_VERB_TENSE = ("vt", "tense")
_VERB_STEM = ("vs", "stem")


def _first_feature(corpus: CorpusHandle, node: int, names: tuple[str, ...]) -> str | None:
    for name in names:
        value = corpus.feature(name, node)
        if value:
            return value
    return None


def _text_of(corpus: CorpusHandle, node: int) -> str:
    """Return rendered text for a node, fallback-safe across corpora."""
    text = corpus.T.text(node)
    if text is None:
        return ""
    return text.strip() if isinstance(text, str) else str(text)


def _ancestor(corpus: CorpusHandle, node: int, otype: str) -> int | None:
    ancestors = corpus.L.u(node, otype=otype)
    return ancestors[0] if ancestors else None


def _descendants(corpus: CorpusHandle, node: int, otype: str) -> list[int]:
    return list(corpus.L.d(node, otype=otype) or [])


# ── Core types ───────────────────────────────────────────────────────────────


@strawberry.type(description="A word token in the corpus with morphological features.")
class Word:
    _corpus_name: strawberry.Private[str]
    _node: strawberry.Private[int]

    text: str = strawberry.field(description="Surface form of the word.")
    lemma: Optional[str] = strawberry.field(description="Dictionary/lexeme form.")
    part_of_speech: Optional[str] = strawberry.field(
        description="Word class (verb, noun, adjective, …).",
    )
    gloss: Optional[str] = strawberry.field(description="Short English gloss.")
    gender: Optional[str] = strawberry.field(description="Grammatical gender.")
    number: Optional[str] = strawberry.field(description="Grammatical number (sg/pl/du).")
    person: Optional[str] = strawberry.field(description="Grammatical person (1/2/3).")
    verb_tense: Optional[str] = strawberry.field(description="Verb tense, if applicable.")
    verb_stem: Optional[str] = strawberry.field(description="Verb stem, if applicable.")

    @strawberry.field(description="Read an arbitrary raw TF/CF feature value.")
    def feature(self, name: str) -> Optional[str]:
        return registry.require(self._corpus_name).feature(name, self._node)

    @strawberry.field(description="The verse this word belongs to.")
    def verse(self) -> Optional["Verse"]:
        corpus = registry.require(self._corpus_name)
        verse_node = _ancestor(corpus, self._node, "verse")
        return None if verse_node is None else _verse_from_node(corpus, verse_node)


@strawberry.type(description="A phrase — a contiguous group of words with a syntactic role.")
class Phrase:
    _corpus_name: strawberry.Private[str]
    _node: strawberry.Private[int]

    text: str = strawberry.field(description="Rendered text of the phrase.")
    function: Optional[str] = strawberry.field(
        description="Syntactic function (Subj, Pred, Objc, …).",
    )
    type: Optional[str] = strawberry.field(description="Phrase type (NP, VP, PP, …).")

    @strawberry.field(description="Words contained in this phrase, in reading order.")
    def words(self) -> list[Word]:
        corpus = registry.require(self._corpus_name)
        return [_word_from_node(corpus, n) for n in _descendants(corpus, self._node, "word")]


@strawberry.type(description="A clause — a syntactic unit built from one or more phrases.")
class Clause:
    _corpus_name: strawberry.Private[str]
    _node: strawberry.Private[int]

    text: str = strawberry.field(description="Rendered text of the clause.")
    type: Optional[str] = strawberry.field(description="Clause type.")

    @strawberry.field(description="Phrases in this clause, in reading order.")
    def phrases(self) -> list[Phrase]:
        corpus = registry.require(self._corpus_name)
        return [_phrase_from_node(corpus, n) for n in _descendants(corpus, self._node, "phrase")]

    @strawberry.field(description="Every word in this clause, in reading order.")
    def words(self) -> list[Word]:
        corpus = registry.require(self._corpus_name)
        return [_word_from_node(corpus, n) for n in _descendants(corpus, self._node, "word")]


@strawberry.type(description="A single verse of text.")
class Verse:
    _corpus_name: strawberry.Private[str]
    _node: strawberry.Private[int]

    reference: str = strawberry.field(description='Canonical reference, e.g. "Genesis 1:1".')
    book_name: str = strawberry.field(description="Book this verse belongs to.")
    chapter_number: int = strawberry.field(description="Chapter number within the book.")
    number: int = strawberry.field(description="Verse number within the chapter.")
    text: str = strawberry.field(description="Rendered text of the verse.")

    @strawberry.field(description="Words in reading order.")
    def words(self) -> list[Word]:
        corpus = registry.require(self._corpus_name)
        return [_word_from_node(corpus, n) for n in _descendants(corpus, self._node, "word")]

    @strawberry.field(description="Clauses in reading order, when the corpus exposes them.")
    def clauses(self) -> list[Clause]:
        corpus = registry.require(self._corpus_name)
        return [_clause_from_node(corpus, n) for n in _descendants(corpus, self._node, "clause")]

    @strawberry.field(description="Phrases in reading order, when the corpus exposes them.")
    def phrases(self) -> list[Phrase]:
        corpus = registry.require(self._corpus_name)
        return [_phrase_from_node(corpus, n) for n in _descendants(corpus, self._node, "phrase")]


@strawberry.type(description="A chapter containing one or more verses.")
class Chapter:
    _corpus_name: strawberry.Private[str]
    _node: strawberry.Private[int]

    book_name: str = strawberry.field(description="Book this chapter belongs to.")
    number: int = strawberry.field(description="Chapter number within the book.")

    @strawberry.field(description="Concatenated chapter text.")
    def text(self) -> str:
        return _text_of(registry.require(self._corpus_name), self._node)

    @strawberry.field(description="Verses in reading order.")
    def verses(self) -> list[Verse]:
        corpus = registry.require(self._corpus_name)
        return [_verse_from_node(corpus, n) for n in _descendants(corpus, self._node, "verse")]

    @strawberry.field(description="Number of verses in this chapter.")
    def verse_count(self) -> int:
        corpus = registry.require(self._corpus_name)
        return len(_descendants(corpus, self._node, "verse"))


@strawberry.type(description="A book in the corpus.")
class Book:
    _corpus_name: strawberry.Private[str]
    _node: strawberry.Private[int]

    name: str = strawberry.field(description="Book name as recorded by the corpus.")

    @strawberry.field(description="Chapters in reading order.")
    def chapters(self) -> list[Chapter]:
        corpus = registry.require(self._corpus_name)
        return [
            _chapter_from_node(corpus, n)
            for n in _descendants(corpus, self._node, "chapter")
        ]

    @strawberry.field(description="Number of chapters in this book.")
    def chapter_count(self) -> int:
        corpus = registry.require(self._corpus_name)
        return len(_descendants(corpus, self._node, "chapter"))

    @strawberry.field(description="Number of words in this book.")
    def word_count(self) -> int:
        corpus = registry.require(self._corpus_name)
        return len(_descendants(corpus, self._node, "word"))


@strawberry.type(description="A corpus loaded into the registry.")
class Corpus:
    name: str = strawberry.field(description="Registered name for this corpus.")
    path: str = strawberry.field(description="Filesystem path the corpus was loaded from.")

    @strawberry.field(description="Object types available in this corpus (word, verse, …).")
    def object_types(self) -> list[str]:
        return registry.require(self.name).object_types()

    @strawberry.field(description="Raw TF/CF feature names available in this corpus.")
    def feature_names(self) -> list[str]:
        return registry.require(self.name).feature_names()

    @strawberry.field(description="Books in this corpus.")
    def books(self) -> list[Book]:
        corpus = registry.require(self.name)
        return [_book_from_node(corpus, n) for n in corpus.F.otype.s("book")]


# ── Inputs ───────────────────────────────────────────────────────────────────


@strawberry.input(
    description=(
        "Filter for `words` queries. Every field is optional and AND-combined, "
        "so you only supply the dimensions you care about. Morphology fields "
        "map onto Text-Fabric feature codes but use natural names "
        "(see https://context-fabric.ai/docs/concepts/text-fabric-compat). "
        "Section scoping (book / chapter / verse) mirrors the canonical "
        "section reference model "
        "(https://context-fabric.ai/docs/concepts/section-references)."
    )
)
class WordFilter:
    # Lexical dimensions
    lemma: Optional[str] = strawberry.field(
        default=None, description="Match lemma exactly (TF: lex).",
    )
    gloss: Optional[str] = strawberry.field(
        default=None, description="Substring match against the English gloss.",
    )
    # Morphology
    part_of_speech: Optional[str] = strawberry.field(
        default=None, description="Match part of speech exactly (TF: sp).",
    )
    verb_stem: Optional[str] = strawberry.field(
        default=None, description="Match verb stem exactly, e.g. 'qal' (TF: vs).",
    )
    verb_tense: Optional[str] = strawberry.field(
        default=None, description="Match verb tense exactly (TF: vt).",
    )
    gender: Optional[str] = strawberry.field(
        default=None, description="Grammatical gender (TF: gn).",
    )
    number: Optional[str] = strawberry.field(
        default=None, description="Grammatical number sg/pl/du (TF: nu).",
    )
    person: Optional[str] = strawberry.field(
        default=None, description="Grammatical person 1/2/3 (TF: ps).",
    )
    # Section scoping — mirrors [book, chapter, verse] section references.
    book: Optional[str] = strawberry.field(
        default=None, description="Limit to this book, e.g. 'Genesis'.",
    )
    chapter: Optional[int] = strawberry.field(
        default=None, description="Limit to this chapter number within the book.",
    )
    verse: Optional[int] = strawberry.field(
        default=None, description="Limit to this verse number within the chapter.",
    )


# ── Search results ───────────────────────────────────────────────────────────


@strawberry.type(description="One match from a search query.")
class SearchMatch:
    reference: Optional[str] = strawberry.field(
        description="Canonical reference of the verse containing the match, if applicable.",
    )
    text: str = strawberry.field(description="Rendered text of the matched nodes.")


# ── Node → type factories ────────────────────────────────────────────────────
# Kept below the type definitions so they can close over the concrete classes.


def _word_from_node(corpus: CorpusHandle, node: int) -> Word:
    return Word(
        _corpus_name=corpus.name,
        _node=node,
        text=_first_feature(corpus, node, _WORD_TEXT_FEATURES) or _text_of(corpus, node),
        lemma=_first_feature(corpus, node, _LEMMA_FEATURES),
        part_of_speech=_first_feature(corpus, node, _PART_OF_SPEECH),
        gloss=_first_feature(corpus, node, _GLOSS_FEATURES),
        gender=_first_feature(corpus, node, _GENDER),
        number=_first_feature(corpus, node, _NUMBER),
        person=_first_feature(corpus, node, _PERSON),
        verb_tense=_first_feature(corpus, node, _VERB_TENSE),
        verb_stem=_first_feature(corpus, node, _VERB_STEM),
    )


def _phrase_from_node(corpus: CorpusHandle, node: int) -> Phrase:
    return Phrase(
        _corpus_name=corpus.name,
        _node=node,
        text=_text_of(corpus, node),
        function=corpus.feature("function", node),
        type=corpus.feature("typ", node),
    )


def _clause_from_node(corpus: CorpusHandle, node: int) -> Clause:
    return Clause(
        _corpus_name=corpus.name,
        _node=node,
        text=_text_of(corpus, node),
        type=corpus.feature("typ", node) or corpus.feature("kind", node),
    )


def _verse_from_node(corpus: CorpusHandle, node: int) -> Verse:
    book_node = _ancestor(corpus, node, "book")
    book_name = (corpus.feature("book", book_node) if book_node else None) or "?"
    chapter_number = int(corpus.feature("chapter", node) or 0)
    verse_number = int(corpus.feature("verse", node) or 0)
    return Verse(
        _corpus_name=corpus.name,
        _node=node,
        reference=format_reference(book_name, chapter_number, verse_number),
        book_name=book_name,
        chapter_number=chapter_number,
        number=verse_number,
        text=_text_of(corpus, node),
    )


def _chapter_from_node(corpus: CorpusHandle, node: int) -> Chapter:
    book_node = _ancestor(corpus, node, "book")
    book_name = (corpus.feature("book", book_node) if book_node else None) or "?"
    chapter_number = int(corpus.feature("chapter", node) or 0)
    return Chapter(
        _corpus_name=corpus.name,
        _node=node,
        book_name=book_name,
        number=chapter_number,
    )


def _book_from_node(corpus: CorpusHandle, node: int) -> Book:
    return Book(
        _corpus_name=corpus.name,
        _node=node,
        name=corpus.feature("book", node) or str(node),
    )


def _corpus_from_handle(handle: CorpusHandle) -> Corpus:
    return Corpus(name=handle.name, path=handle.path)
