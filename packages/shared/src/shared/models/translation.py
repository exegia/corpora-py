from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


class Translation(Base):
	__tablename__ = "translations"

	id: Mapped[str] = mapped_column(String(50), primary_key=True)
	name: Mapped[str] = mapped_column(String(255))
	english_name: Mapped[str] = mapped_column(String(255))
	website: Mapped[str | None] = mapped_column(Text, nullable=True)
	license_url: Mapped[str | None] = mapped_column(Text, nullable=True)
	short_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
	language: Mapped[str] = mapped_column(String(10))
	language_name: Mapped[str] = mapped_column(String(100))
	language_english_name: Mapped[str] = mapped_column(String(100))
	text_direction: Mapped[str] = mapped_column(String(10), default="ltr")
	available_formats: Mapped[list | None] = mapped_column(JSONB, nullable=True)
	number_of_books: Mapped[int] = mapped_column(Integer, default=0)
	total_chapters: Mapped[int] = mapped_column(Integer, default=0)
	total_verses: Mapped[int] = mapped_column(Integer, default=0)

	books: Mapped[list["Book"]] = relationship("Book", back_populates="translation", lazy="select")
	chapters: Mapped[list["Chapter"]] = relationship(
		"Chapter", back_populates="translation", lazy="select"
	)


class Book(Base):
	__tablename__ = "books"

	id: Mapped[str] = mapped_column(String(100), primary_key=True)
	translation_id: Mapped[str] = mapped_column(
		String(50), ForeignKey("translations.id", ondelete="CASCADE"), index=True
	)
	name: Mapped[str] = mapped_column(String(255))
	common_name: Mapped[str] = mapped_column(String(255))
	title: Mapped[str | None] = mapped_column(String(255), nullable=True)
	order: Mapped[int] = mapped_column(Integer)
	number_of_chapters: Mapped[int] = mapped_column(Integer, default=0)
	first_chapter_number: Mapped[int] = mapped_column(Integer, default=1)
	last_chapter_number: Mapped[int] = mapped_column(Integer, default=1)
	total_verses: Mapped[int] = mapped_column(Integer, default=0)
	is_apocryphal: Mapped[bool] = mapped_column(Boolean, default=False)

	translation: Mapped["Translation"] = relationship("Translation", back_populates="books")
	chapters: Mapped[list["Chapter"]] = relationship(
		"Chapter", back_populates="book", lazy="select"
	)


class Chapter(Base):
	__tablename__ = "chapters"

	id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	book_id: Mapped[str] = mapped_column(
		String(100), ForeignKey("books.id", ondelete="CASCADE"), index=True
	)
	translation_id: Mapped[str] = mapped_column(
		String(50), ForeignKey("translations.id", ondelete="CASCADE"), index=True
	)
	chapter_number: Mapped[int] = mapped_column(Integer)
	number_of_verses: Mapped[int] = mapped_column(Integer, default=0)
	content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
	audio_links: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

	book: Mapped["Book"] = relationship("Book", back_populates="chapters")
	translation: Mapped["Translation"] = relationship("Translation", back_populates="chapters")
