from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


class Dataset(Base):
	__tablename__ = "datasets"

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
	number_of_books: Mapped[int] = mapped_column(Integer, default=0)
	total_chapters: Mapped[int] = mapped_column(Integer, default=0)

	books: Mapped[list["DatasetBook"]] = relationship(
		"DatasetBook", back_populates="dataset", lazy="select"
	)
	chapters: Mapped[list["DatasetChapter"]] = relationship(
		"DatasetChapter", back_populates="dataset", lazy="select"
	)


class DatasetBook(Base):
	__tablename__ = "dataset_books"

	id: Mapped[str] = mapped_column(String(100), primary_key=True)
	dataset_id: Mapped[str] = mapped_column(
		String(50), ForeignKey("datasets.id", ondelete="CASCADE"), index=True
	)
	name: Mapped[str] = mapped_column(String(255))
	common_name: Mapped[str] = mapped_column(String(255))
	title: Mapped[str | None] = mapped_column(String(255), nullable=True)
	order: Mapped[int] = mapped_column(Integer)
	number_of_chapters: Mapped[int] = mapped_column(Integer, default=0)
	first_chapter_number: Mapped[int] = mapped_column(Integer, default=1)
	last_chapter_number: Mapped[int] = mapped_column(Integer, default=1)
	is_apocryphal: Mapped[bool] = mapped_column(Boolean, default=False)

	dataset: Mapped["Dataset"] = relationship("Dataset", back_populates="books")
	chapters: Mapped[list["DatasetChapter"]] = relationship(
		"DatasetChapter", back_populates="book", lazy="select"
	)


class DatasetChapter(Base):
	__tablename__ = "dataset_chapters"

	id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	book_id: Mapped[str] = mapped_column(
		String(100), ForeignKey("dataset_books.id", ondelete="CASCADE"), index=True
	)
	dataset_id: Mapped[str] = mapped_column(
		String(50), ForeignKey("datasets.id", ondelete="CASCADE"), index=True
	)
	chapter_number: Mapped[int] = mapped_column(Integer)
	content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

	book: Mapped["DatasetBook"] = relationship("DatasetBook", back_populates="chapters")
	dataset: Mapped["Dataset"] = relationship("Dataset", back_populates="chapters")
