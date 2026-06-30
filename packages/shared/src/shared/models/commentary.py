from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


class Commentary(Base):
	__tablename__ = "commentaries"

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
	introduction: Mapped[str | None] = mapped_column(Text, nullable=True)
	number_of_books: Mapped[int] = mapped_column(Integer, default=0)
	total_chapters: Mapped[int] = mapped_column(Integer, default=0)

	books: Mapped[list["CommentaryBook"]] = relationship(
		"CommentaryBook", back_populates="commentary", lazy="select"
	)
	chapters: Mapped[list["CommentaryChapter"]] = relationship(
		"CommentaryChapter", back_populates="commentary", lazy="select"
	)
	profiles: Mapped[list["CommentaryProfile"]] = relationship(
		"CommentaryProfile", back_populates="commentary", lazy="select"
	)


class CommentaryBook(Base):
	__tablename__ = "commentary_books"

	id: Mapped[str] = mapped_column(String(100), primary_key=True)
	commentary_id: Mapped[str] = mapped_column(
		String(50), ForeignKey("commentaries.id", ondelete="CASCADE"), index=True
	)
	name: Mapped[str] = mapped_column(String(255))
	common_name: Mapped[str] = mapped_column(String(255))
	title: Mapped[str | None] = mapped_column(String(255), nullable=True)
	order: Mapped[int] = mapped_column(Integer)
	number_of_chapters: Mapped[int] = mapped_column(Integer, default=0)
	first_chapter_number: Mapped[int] = mapped_column(Integer, default=1)
	last_chapter_number: Mapped[int] = mapped_column(Integer, default=1)
	is_apocryphal: Mapped[bool] = mapped_column(Boolean, default=False)

	commentary: Mapped["Commentary"] = relationship("Commentary", back_populates="books")
	chapters: Mapped[list["CommentaryChapter"]] = relationship(
		"CommentaryChapter", back_populates="book", lazy="select"
	)


class CommentaryChapter(Base):
	__tablename__ = "commentary_chapters"

	id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	book_id: Mapped[str] = mapped_column(
		String(100), ForeignKey("commentary_books.id", ondelete="CASCADE"), index=True
	)
	commentary_id: Mapped[str] = mapped_column(
		String(50), ForeignKey("commentaries.id", ondelete="CASCADE"), index=True
	)
	chapter_number: Mapped[int] = mapped_column(Integer)
	content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

	book: Mapped["CommentaryBook"] = relationship("CommentaryBook", back_populates="chapters")
	commentary: Mapped["Commentary"] = relationship("Commentary", back_populates="chapters")


class CommentaryProfile(Base):
	__tablename__ = "commentary_profiles"

	id: Mapped[str] = mapped_column(String(100), primary_key=True)
	commentary_id: Mapped[str] = mapped_column(
		String(50), ForeignKey("commentaries.id", ondelete="CASCADE"), index=True
	)
	name: Mapped[str] = mapped_column(String(255))
	introduction: Mapped[str | None] = mapped_column(Text, nullable=True)
	content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

	commentary: Mapped["Commentary"] = relationship("Commentary", back_populates="profiles")
