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
