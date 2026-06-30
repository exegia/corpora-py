"""
GraphQL Types for Corpus Operations

Defines Strawberry GraphQL types for Context-Fabric corpus queries and operations.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

import strawberry


@strawberry.type
class CorpusMetadata:
    """Metadata about a Text-Fabric corpus."""

    dataset_id: str
    name: str
    language: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None
    total_nodes: Optional[int] = None
    total_features: Optional[int] = None


@strawberry.type
class CorpusFeature:
    """Feature information from Text-Fabric corpus."""

    name: str
    description: Optional[str] = None
    feature_type: Optional[str] = None
    value_type: Optional[str] = None


@strawberry.type
class CorpusNode:
    """Node in the Text-Fabric corpus graph."""

    node_id: int
    node_type: str
    text: Optional[str] = None
    features: Optional[strawberry.scalars.JSON] = None


@strawberry.type
class Verse:
    """Biblical verse from corpus."""

    reference: str
    book: str
    chapter: int
    verse: int
    text: str
    dataset_id: str


@strawberry.type
class Passage:
    """Biblical passage (one or more verses)."""

    reference: str
    book: str
    chapter: int
    start_verse: int
    end_verse: Optional[int] = None
    text: str
    verses: Optional[List[Verse]] = None
    dataset_id: str


@strawberry.type
class SearchResult:
    """Result from corpus search."""

    reference: str
    text: str
    context: Optional[str] = None
    book: str
    chapter: int
    verse: int
    dataset_id: str
    relevance: Optional[float] = None


@strawberry.type
class SearchResults:
    """Paginated search results."""

    results: List[SearchResult]
    total: int
    query: str
    dataset_id: str
    has_more: bool


@strawberry.type
class WordOccurrence:
    """Word occurrence in corpus."""

    word: str
    reference: str
    text: str
    book: str
    chapter: int
    verse: int
    position: int


@strawberry.type
class WordStudy:
    """Word study results."""

    word: str
    lemma: Optional[str] = None
    occurrences: List[WordOccurrence]
    total_count: int
    dataset_id: str


@strawberry.type
class CorpusStats:
    """Statistics about a corpus."""

    dataset_id: str
    total_books: int
    total_chapters: int
    total_verses: int
    total_words: int
    languages: List[str]


@strawberry.type
class BookInfo:
    """Information about a book in the corpus."""

    name: str
    code: str
    testament: Optional[str] = None
    chapter_count: int
    verse_count: int
    word_count: Optional[int] = None


@strawberry.type
class ChapterInfo:
    """Information about a chapter."""

    book: str
    chapter: int
    verse_count: int
    word_count: Optional[int] = None


@strawberry.type
class VerseRange:
    """Range of verses."""

    book: str
    start_chapter: int
    start_verse: int
    end_chapter: int
    end_verse: int
    reference: str


@strawberry.type
class CrossReference:
    """Cross-reference between passages."""

    from_reference: str
    to_reference: str
    relationship_type: Optional[str] = None
    notes: Optional[str] = None


@strawberry.type
class ParallelPassage:
    """Parallel passage across datasets."""

    reference: str
    datasets: List[str]
    texts: strawberry.scalars.JSON


@strawberry.type
class CorpusQueryResult:
    """Result of a corpus query."""

    success: bool
    data: Optional[strawberry.scalars.JSON] = None
    error_message: Optional[str] = None


# Input Types


@strawberry.input
class SearchCorpusInput:
    """Input for searching a corpus."""

    dataset_id: str
    query: str
    limit: int = 50
    offset: int = 0
    books: Optional[List[str]] = None
    testament: Optional[str] = None


@strawberry.input
class GetPassageInput:
    """Input for getting a passage."""

    dataset_id: str
    reference: str
    include_context: bool = False
    context_verses: int = 0


@strawberry.input
class GetPassagesInput:
    """Input for getting multiple passages."""

    dataset_id: str
    references: List[str]
    include_context: bool = False


@strawberry.input
class WordStudyInput:
    """Input for word study."""

    dataset_id: str
    word: str
    lemma: Optional[str] = None
    limit: int = 100


@strawberry.input
class ComparePassagesInput:
    """Input for comparing passages across datasets."""

    reference: str
    dataset_ids: List[str]


@strawberry.input
class GetVerseRangeInput:
    """Input for getting a range of verses."""

    dataset_id: str
    book: str
    start_chapter: int
    start_verse: int
    end_chapter: Optional[int] = None
    end_verse: Optional[int] = None


@strawberry.input
class CorpusQueryInput:
    """Input for advanced corpus query."""

    dataset_id: str
    query_type: str
    parameters: strawberry.scalars.JSON


@strawberry.input
class GetBooksInput:
    """Input for getting book list."""

    dataset_id: str
    testament: Optional[str] = None


@strawberry.input
class GetChapterInfoInput:
    """Input for getting chapter information."""

    dataset_id: str
    book: str
    chapter: int


# User-Friendly Query Types


@strawberry.enum
class NodeType(Enum):
    """
    Available node types in a corpus graph.

    These represent different levels of the text hierarchy:
    - SLOT/WORD: The atomic units (individual words)
    - PHRASE: Groups of words forming phrases
    - CLAUSE: Grammatical clauses
    - SENTENCE: Complete sentences
    - VERSE: Biblical verses
    - CHAPTER: Chapters
    - BOOK: Entire books
    - DOCUMENT: Complete documents
    """

    DOCUMENT = "document"
    BOOK = "book"
    CHAPTER = "chapter"
    VERSE = "verse"
    SENTENCE = "sentence"
    CLAUSE = "clause"
    PHRASE = "phrase"
    WORD = "word"
    SLOT = "slot"


@strawberry.enum
class OrderConstraint(Enum):
    """
    Ordering constraints for node relationships in search patterns.

    - BEFORE: First node must come before second node
    - AFTER: First node must come after second node
    - ADJACENT: Nodes must be directly adjacent
    """

    BEFORE = "<"
    AFTER = ">"
    ADJACENT = ".."


@strawberry.input
class FeatureFilter:
    """
    Filter nodes by feature values.

    Examples:
    - {"name": "pos", "value": "verb", "operator": "="}
    - {"name": "tense", "value": "past", "operator": "="}
    - {"name": "lemma", "value": "love", "operator": "~"}  # case-insensitive
    """

    name: str
    value: str
    operator: str = "="  # =, !=, ~, !~


@strawberry.input
class NodeQuery:
    """
    Query parameters for a single node in a search pattern.

    Examples:
    - Find verbs: {node_type: WORD, features: [{name: "pos", value: "verb"}]}
    - Find subject phrases: {node_type: PHRASE, features: [{name: "function", value: "subject"}]}
    """

    node_type: NodeType
    features: Optional[List[FeatureFilter]] = None
    quantifier: Optional[str] = None  # *, +, ?, {n}, {n,m}
    label: Optional[str] = None  # For referencing in results


@strawberry.input
class SearchPattern:
    """
    Hierarchical search pattern for corpus queries.

    Build complex queries by nesting nodes in parent-child relationships.

    Example: Find clauses with subject before predicate
    {
      root: {node_type: CLAUSE},
      children: [
        {node_type: PHRASE, features: [{name: "function", value: "subject"}]},
        {node_type: PHRASE, features: [{name: "function", value: "predicate"}], order_constraint: AFTER}
      ]
    }
    """

    root: NodeQuery
    children: Optional[List["SearchPattern"]] = None
    order_constraint: Optional[OrderConstraint] = None


@strawberry.type
class NodeResult:
    """
    A single node in search results with its text and features.
    """

    node_id: int
    node_type: str
    text: str
    features: strawberry.scalars.JSON

    @strawberry.field
    def feature(self, name: str) -> Optional[str]:
        """Get a specific feature value by name"""
        return self.features.get(name)


@strawberry.type
class CorpusInfo:
    """
    Metadata and statistics about a loaded corpus.
    """

    dataset_id: str
    node_types: List[str]
    features: List[str]
    total_slots: int
    description: Optional[str] = None
