"""
Generic book models — designed to be agnostic to book structure.

Three tables:

  library_books   — top-level catalog entry for any imported book.
  book_sections   — a node in the content hierarchy (self-referential).
                    Handles any depth: part → chapter → section → sub-section.
                    Books with no hierarchy just have flat root-level sections.
  book_pages      — the smallest addressable content unit (spine item, page,
                    verse-equivalent, dictionary entry, etc.).

A book with chapters:
  LibraryBook → BookSection(type=chapter, level=0) → BookPage(s)

A flat book (no chapters):
  LibraryBook → BookPage(s)   (section_uuid=None)

A deeply nested book:
  LibraryBook
    └─ BookSection(part, level=0)
         └─ BookSection(chapter, level=1)
              └─ BookSection(section, level=2)
                   └─ BookPage(s)
"""

import enum
import uuid as _uuid_module
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


# ── Enumerations ──────────────────────────────────────────────────────────────


class BookCategory(str, enum.Enum):
	BIBLE = "bible"
	QURAN = "quran"
	TANAKH = "tanakh"
	COMMENTARY = "commentary"
	LEXICON = "lexicon"
	DICTIONARY = "dictionary"
	DEVOTIONAL = "devotional"
	THEOLOGY = "theology"
	HISTORY = "history"
	PHILOSOPHY = "philosophy"
	FICTION = "fiction"
	OTHER = "other"


class BookSourceType(str, enum.Enum):
	EPUB = "epub"
	PDF = "pdf"
	URL = "url"
	MANUAL = "manual"


class SectionType(str, enum.Enum):
	PART = "part"
	CHAPTER = "chapter"
	SECTION = "section"
	ARTICLE = "article"
	ENTRY = "entry"
	APPENDIX = "appendix"
	INTRODUCTION = "introduction"
	PREFACE = "preface"
	FOREWORD = "foreword"
	INDEX = "index"
	GLOSSARY = "glossary"
	OTHER = "other"


def _new_uuid() -> str:
	return str(_uuid_module.uuid4())


# ── Models ────────────────────────────────────────────────────────────────────


class LibraryBook(Base):
	"""
	Top-level catalog entry for any imported or manually created book.

	All fields beyond `uuid`, `slug`, `title`, and `category` are optional
	so the model can represent anything from a Bible translation to a novel.
	"""

	__tablename__ = "library_books"

	uuid: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
	slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)

	# ── Identity ──────────────────────────────────────────────────────────────
	title: Mapped[str] = mapped_column(String(500))
	subtitle: Mapped[str | None] = mapped_column(String(500), nullable=True)
	# ["First Author", "Second Author"]
	authors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
	publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
	published_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
	language: Mapped[str] = mapped_column(String(10), default="en")
	text_direction: Mapped[str] = mapped_column(String(3), default="ltr")

	# ── Classification ────────────────────────────────────────────────────────
	category: Mapped[BookCategory] = mapped_column(
		Enum(BookCategory, name="book_category"),
		default=BookCategory.OTHER,
		index=True,
	)
	# ["subject1", "subject2", ...]
	subjects: Mapped[list | None] = mapped_column(JSONB, nullable=True)

	# ── Origin ────────────────────────────────────────────────────────────────
	source_type: Mapped[BookSourceType] = mapped_column(
		Enum(BookSourceType, name="book_source_type"),
		default=BookSourceType.MANUAL,
	)
	source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)

	# ── Assets & rights ───────────────────────────────────────────────────────
	cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
	description: Mapped[str | None] = mapped_column(Text, nullable=True)
	website: Mapped[str | None] = mapped_column(Text, nullable=True)
	license: Mapped[str | None] = mapped_column(String(100), nullable=True)
	license_url: Mapped[str | None] = mapped_column(Text, nullable=True)

	# ── Denormalised counters (updated by service layer) ──────────────────────
	total_sections: Mapped[int] = mapped_column(Integer, default=0)
	total_pages: Mapped[int] = mapped_column(Integer, default=0)

	# ── Escape hatch for source-specific metadata ─────────────────────────────
	extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

	# ── Timestamps ────────────────────────────────────────────────────────────
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), server_default=func.now(), nullable=False
	)
	updated_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
	)

	# ── Relationships ──────────────────────────────────────────────────────────
	sections: Mapped[list["BookSection"]] = relationship(
		"BookSection",
		back_populates="book",
		foreign_keys="BookSection.book_uuid",
		cascade="all, delete-orphan",
		lazy="select",
	)
	pages: Mapped[list["BookPage"]] = relationship(
		"BookPage",
		back_populates="book",
		cascade="all, delete-orphan",
		lazy="select",
	)


class BookSection(Base):
	"""
	A node in the book's content hierarchy.

	`parent_uuid` is self-referential, making the depth unlimited.
	`level` is a convenience denormalisation (0 = root, 1 = child, …).
	`order` is the position among siblings with the same parent.

	Books that have no structural hierarchy can omit sections entirely
	and attach pages directly to the book.
	"""

	__tablename__ = "book_sections"

	uuid: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
	book_uuid: Mapped[str] = mapped_column(
		String, ForeignKey("library_books.uuid", ondelete="CASCADE"), index=True
	)
	parent_uuid: Mapped[str | None] = mapped_column(
		String,
		ForeignKey("book_sections.uuid", ondelete="CASCADE"),
		nullable=True,
		index=True,
	)

	title: Mapped[str | None] = mapped_column(String(500), nullable=True)
	section_type: Mapped[SectionType] = mapped_column(
		Enum(SectionType, name="book_section_type"),
		default=SectionType.CHAPTER,
	)
	# Depth from the root (0 = top-level, 1 = sub-section, …)
	level: Mapped[int] = mapped_column(Integer, default=0)
	# Position among siblings with the same parent
	order: Mapped[int] = mapped_column(Integer, default=0)

	total_pages: Mapped[int] = mapped_column(Integer, default=0)
	extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

	# ── Relationships ──────────────────────────────────────────────────────────
	book: Mapped["LibraryBook"] = relationship(
		"LibraryBook",
		back_populates="sections",
		foreign_keys=[book_uuid],
	)
	parent: Mapped["BookSection | None"] = relationship(
		"BookSection",
		back_populates="children",
		remote_side="BookSection.uuid",
	)
	children: Mapped[list["BookSection"]] = relationship(
		"BookSection",
		back_populates="parent",
		cascade="all, delete-orphan",
		lazy="select",
	)
	pages: Mapped[list["BookPage"]] = relationship(
		"BookPage",
		back_populates="section",
		lazy="select",
	)


class BookPage(Base):
	"""
	The smallest addressable content unit in a book.

	`book_index`    — absolute position across the whole book (0-based).
	`section_index` — position within the parent section (0-based).
	`section_uuid`  — nullable; pages can belong directly to a book when the
	                  book has no structural hierarchy.
	`html`          — cleaned semantic HTML (output of the EPUB cleaner or
	                  any other parser).
	`text`          — plain-text version for full-text search / indexing.
	"""

	__tablename__ = "book_pages"

	uuid: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
	book_uuid: Mapped[str] = mapped_column(
		String, ForeignKey("library_books.uuid", ondelete="CASCADE"), index=True
	)
	section_uuid: Mapped[str | None] = mapped_column(
		String,
		ForeignKey("book_sections.uuid", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)

	title: Mapped[str | None] = mapped_column(String(500), nullable=True)
	# Absolute position in the book (used for ordered retrieval)
	book_index: Mapped[int] = mapped_column(Integer, default=0, index=True)
	# Position within the parent section
	section_index: Mapped[int] = mapped_column(Integer, default=0)

	html: Mapped[str | None] = mapped_column(Text, nullable=True)
	text: Mapped[str | None] = mapped_column(Text, nullable=True)

	extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

	# ── Relationships ──────────────────────────────────────────────────────────
	book: Mapped["LibraryBook"] = relationship("LibraryBook", back_populates="pages")
	section: Mapped["BookSection | None"] = relationship(
		"BookSection", back_populates="pages"
	)
