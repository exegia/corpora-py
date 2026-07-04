"""Tests for the EPUB -> Text-Fabric converter (admin.utils.convert_epub_to_tf).

Requires the admin [full] extra (text-fabric): uv sync --extra full
"""

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("tf", reason="text-fabric not installed (admin [full] extra)")

from admin.utils.convert_epub_to_tf import convert_epub_to_tf  # noqa: E402
from shared.corpus import validate_corpus  # noqa: E402

# 1x1 transparent PNG
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f0005fe02fea72d5e4b0000000049454e44ae426082"
)

_MATTHEW = """<html><body>
<h1>The Gospel According to Matthew</h1>
<h2>Chapter 1</h2>
<p><sup>1</sup>The book of the genealogy of Jesus Christ, the son of David.
<sup>2</sup>Abraham was the father of Isaac, and Isaac the father of Jacob;
and Jacob the father of Judah.</p>
<p><sup>3</sup>And Judah the father of Perez and Zerah by Tamar.</p>
<h2>Chapter 2</h2>
<p><sup>1</sup>Now when Jesus was born in Bethlehem of Judea, wise men came,
<sup>2</sup>saying, Where is he who has been born king of the Jews?</p>
<img src="../images/map.png" alt="Map of Judea"/>
</body></html>"""

_MARK = """<html><body>
<h1>The Gospel According to Mark</h1>
<h2>Chapter 1</h2>
<p><sup>1</sup>The beginning of the gospel of Jesus Christ, the Son of God.
<sup>2</sup>As it is written in Isaiah the prophet: Behold, I send my messenger.</p>
</body></html>"""


def _write_epub(path: Path, title: str, chapters: list[tuple[str, str, str]], image: bool = False):
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier(f"test-{title}")
    book.set_title(title)
    book.set_language("en")
    book.add_author("Test Author")

    if image:
        book.add_item(
            epub.EpubItem(
                uid="img1",
                file_name="images/map.png",
                media_type="image/png",
                content=_PNG,
            )
        )

    spine: list = ["nav"]
    for name, chapter_title, html in chapters:
        item = epub.EpubHtml(title=chapter_title, file_name=name)
        item.content = html
        book.add_item(item)
        spine.append(item)

    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)
    return path


@pytest.fixture(scope="module")
def bible_tf(tmp_path_factory) -> Path:
    """Convert a scripture-style EPUB (verse markers, chapters, image) once."""
    base = tmp_path_factory.mktemp("bible")
    epub_path = _write_epub(
        base / "bible.epub",
        "Mini SBL Test Bible",
        [("matthew.xhtml", "Matthew", _MATTHEW), ("mark.xhtml", "Mark", _MARK)],
        image=True,
    )
    return convert_epub_to_tf(epub_path, base / "tf_out", corpus_name="MiniSBL")


@pytest.fixture(scope="module")
def bible_api(bible_tf: Path):
    import cfabric

    return cfabric.Fabric(locations=str(bible_tf), silent="deep").loadAll(silent="deep")


@pytest.fixture(scope="module")
def novel_tf(tmp_path_factory) -> Path:
    """Convert a regular prose EPUB (no verse markers) once."""
    base = tmp_path_factory.mktemp("novel")
    epub_path = _write_epub(
        base / "novel.epub",
        "A Regular Novel",
        [
            (
                "ch1.xhtml",
                "One",
                "<html><body><h2>The Beginning</h2>"
                "<p>It was a dark and stormy night; the rain fell in torrents. "
                'Everyone stayed inside. See <a href="https://example.com/n">notes</a>.</p>'
                "</body></html>",
            ),
            (
                "ch2.xhtml",
                "Two",
                "<html><body><h2>The Middle</h2>"
                "<p>Morning came, and with it hope. The storm had passed!</p></body></html>",
            ),
        ],
    )
    return convert_epub_to_tf(epub_path, base / "tf_out")


# ── Scripture mode ────────────────────────────────────────────────────────────


def test_bible_has_scripture_sections(bible_tf: Path, bible_api):
    otext = (bible_tf / "otext.tf").read_text()
    assert "@sectionTypes=book,chapter,verse" in otext
    assert "@sectionFeatures=book,chapter,verse" in otext
    assert bible_api.T.sectionTypes == ["book", "chapter", "verse"]


def test_bible_node_types(bible_api):
    types = set(bible_api.F.otype.all)
    assert {"book", "chapter", "verse", "sentence", "clause", "word"} <= types


def test_bible_section_lookup(bible_api):
    node = bible_api.T.nodeFromSection(("The Gospel According to Matthew", 1, 2))
    assert node is not None
    text = bible_api.T.text(node)
    assert "Abraham was the father of Isaac" in text

    node = bible_api.T.nodeFromSection(("The Gospel According to Mark", 1, 1))
    assert "The beginning of the gospel" in bible_api.T.text(node)


def test_bible_books_and_chapters(bible_api):
    books = bible_api.F.otype.s("book")
    assert len(books) == 2  # nav page excluded
    chapters = bible_api.F.otype.s("chapter")
    assert [bible_api.Fs("chapter").v(c) for c in chapters] == [1, 2, 1]


def test_bible_clauses_within_sentences(bible_api):
    sentences = bible_api.F.otype.s("sentence")
    clauses = bible_api.F.otype.s("clause")
    assert len(sentences) > 0
    assert len(clauses) > len(sentences)  # commas split clauses within sentences
    # "Abraham was the father of Isaac, and Isaac ..., and Jacob ..." -> 3 clauses
    verse = bible_api.T.nodeFromSection(("The Gospel According to Matthew", 1, 2))
    verse_slots = set(bible_api.Es("oslots").s(verse))
    verse_clauses = [c for c in clauses if set(bible_api.Es("oslots").s(c)) <= verse_slots]
    assert len(verse_clauses) == 3


def test_bible_image_asset_extracted(bible_tf: Path, bible_api):
    assert (bible_tf / "assets" / "images" / "map.png").read_bytes() == _PNG
    images = bible_api.F.otype.s("image")
    assert len(images) == 1
    img = images[0]
    assert bible_api.Fs("asset").v(img) == "assets/images/map.png"
    assert bible_api.Fs("alt").v(img) == "Map of Judea"


def test_bible_word_features(bible_api):
    words = bible_api.F.otype.s("word")
    texts = [bible_api.Fs("text").v(w) for w in words[:3]]
    assert texts == ["The", "book", "of"]
    # punctuation lands in `after`, not in the word text
    afters = {bible_api.Fs("after").v(w) for w in words}
    assert any("." in a for a in afters)


def test_bible_passes_validation(bible_tf: Path):
    result = validate_corpus("MiniSBL", bible_tf)
    assert result.is_valid, result.failure_reasons()


# ── Regular mode ──────────────────────────────────────────────────────────────


def test_novel_has_book_chapter_sections(novel_tf: Path):
    otext = (novel_tf / "otext.tf").read_text()
    assert "@sectionTypes=book,chapter" in otext
    assert "verse" not in otext


def test_novel_structure(novel_tf: Path):
    import cfabric

    api: Any = cfabric.Fabric(locations=str(novel_tf), silent="deep").loadAll(silent="deep")
    assert "verse" not in api.F.otype.all
    chapters = api.F.otype.s("chapter")
    assert len(chapters) == 2  # nav page excluded
    assert api.Fs("title").v(chapters[0]) == "The Beginning"
    links = api.F.otype.s("link")
    assert api.Fs("href").v(links[0]) == "https://example.com/n"
    # sentence and clause segmentation applies to regular prose too
    assert len(api.F.otype.s("sentence")) >= 4
    assert len(api.F.otype.s("clause")) > len(api.F.otype.s("sentence"))


def test_novel_passes_validation(novel_tf: Path):
    result = validate_corpus("novel", novel_tf)
    assert result.is_valid, result.failure_reasons()
