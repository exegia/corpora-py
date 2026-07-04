"""
EPUB to Text-Fabric Converter

Converts EPUB ebook files into Text-Fabric datasets using the epub service
for parsing and the tf.convert.walker library for TF generation.

Features:
<<<<<<< HEAD
- Extracts EPUB metadata (title, author, publisher, etc.)
- Preserves book structure (chapters/pages)
- Converts HTML content to queryable nodes
- Creates semantic nodes from clean HTML
- Tracks conversion progress

Node Types:
- book: Root node for the entire EPUB
- chapter: Individual pages/chapters from the EPUB
- element: HTML elements from page content
- paragraph: Paragraph-like elements
- link: Link elements with href
- word: Individual words (slots)
=======
- Extracts EPUB metadata (title, author, publisher, etc.) into feature headers
- Extracts binary assets (images, cover) into an assets/ directory
- Configures otext sections (book > chapter > verse, or book > chapter)
- Segments text into sentences and clauses by punctuation
- Detects scripture-style content (verse markers) and emits verse nodes

Node types:
- book:      one per spine document in scripture mode, or the whole EPUB
- chapter:   detected chapter (scripture) or spine document (regular)
- verse:     scripture verse, from <sup>N</sup>-style markers
- paragraph: block-level elements (p, blockquote, headings, list items, ...)
- sentence:  punctuation-segmented sentence
- clause:    punctuation-segmented clause within a sentence
- link:      <a> elements with href
- table/row/cell: table structure
- image:     <img> elements, linked to extracted assets
- word:      individual tokens (slots), with text and after features

The output aims to be close to hand-built scripture corpora such as
CenterBLC/SBLGNT (book/chapter/verse sections, sentence and clause nodes),
while degrading gracefully for regular books and documents.
>>>>>>> origin/dev

Usage:
    from admin.utils.convert_epub_to_tf import convert_epub_to_tf

    tf_path = convert_epub_to_tf(
        epub_path="book.epub",
        output_dir="tf_output/",
        corpus_name="MyBook"
    )
"""

<<<<<<< HEAD
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from bs4 import BeautifulSoup, NavigableString, Tag
from tf.convert.walker import CV

from shared.utils.parse_epub import extract_pages, get_metadata
=======
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString, PageElement, Tag
from shared.utils.parse_epub import extract_assets, extract_pages, get_metadata

# Sentence-ending / clause-ending punctuation. Greek uses ";" as the question
# mark and "·" (ano teleia) as the semicolon, so both close a clause here and
# "." "!" "?" close a sentence.
_SENTENCE_END = set(".!?…")
_CLAUSE_END = set(",;:·—")
_STRIP_PUNCT = ".,;:!?·…—\"'»”’)]}"

_BLOCK_TAGS = {
    "p", "blockquote", "pre", "li", "dt", "dd", "figcaption",
    "h1", "h2", "h3", "h4", "h5", "h6",
}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

_VERSE_MARKER = re.compile(r"^\d{1,3}$")
_TRAILING_INT = re.compile(r"(\d{1,3})\s*$")

# Minimum number of <sup>N</sup> markers across the EPUB before we treat it
# as scripture with book/chapter/verse sections.
_SCRIPTURE_THRESHOLD = 5
>>>>>>> origin/dev


class EPUBToTFConverter:
    """
    Converts EPUB files to Text-Fabric format.

    Uses the epub service to parse EPUB files and extracts clean HTML,
<<<<<<< HEAD
    then converts to TF using the walker API.
=======
    then converts to TF using the tf.convert.walker API.
>>>>>>> origin/dev
    """

    def __init__(
        self,
<<<<<<< HEAD
        epub_path: Union[str, Path],
        output_dir: Union[str, Path],
        corpus_name: Optional[str] = None,
        version: str = "1.0",
        tokenize: bool = True,
        on_progress: Optional[Callable[[int, int, float], None]] = None,
=======
        epub_path: str | Path,
        output_dir: str | Path,
        corpus_name: str | None = None,
        version: str = "1.0",
        tokenize: bool = True,
        on_progress: Callable[[int, int, float], None] | None = None,
>>>>>>> origin/dev
    ):
        """
        Initialize the EPUB to TF converter.

        Args:
            epub_path: Path or URL to EPUB file
            output_dir: Directory where TF files will be created
            corpus_name: Name of the corpus (defaults to EPUB title)
            version: Version string
            tokenize: If True, split text into word slots
            on_progress: Optional callback(current, total, percent)
        """
        self.epub_path = str(epub_path)
        self.output_dir = Path(output_dir)
        self.corpus_name = corpus_name
        self.version = version
        self.tokenize = tokenize
        self.on_progress = on_progress

<<<<<<< HEAD
        # Converter instance (initialized in convert())
        self.cv = None

        # EPUB metadata
        self.metadata = {}
        self.pages = []
=======
        self.metadata: dict[str, Any] = {}
        self.pages: list[dict[str, Any]] = []
        self.content_pages: list[dict[str, Any]] = []
        self.scripture = False

        # Walker state (set during cv.walk)
        self.cv: Any = None
        self._book: Any = None
        self._chapter: Any = None
        self._verse: Any = None
        self._sentence: Any = None
        self._clause: Any = None
        self._chapter_num = 0
        self._verse_num = 0
        self._sentence_num = 0
        self._clause_num = 0
        self._chapter_from_heading = False
        self._asset_map: dict[str, str] = {}

    # ── Top level ─────────────────────────────────────────────────────────────
>>>>>>> origin/dev

    def convert(self) -> Path:
        """
        Convert EPUB to Text-Fabric format.

        Returns:
<<<<<<< HEAD
            Path to the generated TF directory
        """
        print(f"Loading EPUB: {self.epub_path}")

        # Extract metadata
        self.metadata = get_metadata(self.epub_path)

        # Use title as corpus name if not provided
=======
            Path to the generated TF dataset directory.
        """
        from tf.convert.walker import CV
        from tf.fabric import Fabric

        print(f"Loading EPUB: {self.epub_path}")
        self.metadata = get_metadata(self.epub_path)

>>>>>>> origin/dev
        if not self.corpus_name:
            titles = self.metadata.get("title", [])
            self.corpus_name = titles[0] if titles else "EPUBCorpus"

        print(f"Title: {self.corpus_name}")
<<<<<<< HEAD
        print(f"Total pages: {self.metadata.get('total_pages', 0)}")

        # Extract pages
=======

>>>>>>> origin/dev
        print("Extracting pages...")
        self.pages = extract_pages(
            self.epub_path,
            on_progress=self._handle_extraction_progress,
        )
<<<<<<< HEAD

        print(f"✅ Extracted {len(self.pages)} pages")

        # Initialize TF converter
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.cv = CV(
            location=str(self.output_dir),
            module=self.corpus_name,
            version=self.version,
        )

        # Define metadata
        self._define_metadata()

        # Walk through the EPUB structure
        self._walk_epub()

        # Generate TF files
        tf_path = self.cv.terminate()

        print(f"✅ Conversion complete! TF files created at: {tf_path}")
        return Path(tf_path)
=======
        print(f"Extracted {len(self.pages)} pages")

        self.scripture = self._detect_scripture()
        mode = "scripture (book/chapter/verse)" if self.scripture else "regular (book/chapter)"
        print(f"Detected content type: {mode}")

        dataset_dir = self.output_dir / self.corpus_name / "tf" / self.version
        dataset_dir.mkdir(parents=True, exist_ok=True)

        self._extract_assets(dataset_dir)

        self.content_pages = [
            p
            for p in self.pages
            if (p["text"].strip() or "<img" in p["html"]) and not self._is_navigation(p)
        ]

        used = self._scan_used_features()
        int_features = {"chapter", "sentence", "clause", "chapter_index"} & used
        if self.scripture:
            int_features.add("verse")

        tf = Fabric(locations=str(dataset_dir), silent="deep")
        cv = CV(tf, silent="deep")
        good = cv.walk(
            self._director,
            slotType="word",
            otext=self._otext(),
            generic=self._generic_metadata(),
            intFeatures=int_features,
            featureMeta=self._feature_meta(used),
            warn=None,  # report irregularities but do not abort a heuristic conversion
            force=True,
        )
        if not good:
            raise RuntimeError(f"Text-Fabric conversion failed for {self.epub_path}")

        print(f"Conversion complete! TF files created at: {dataset_dir}")
        return dataset_dir
>>>>>>> origin/dev

    def _handle_extraction_progress(self, current: int, total: int, percent: float):
        """Handle progress callback from EPUB extraction."""
        if self.on_progress:
            self.on_progress(current, total, percent)
        else:
            print(f"  Extracting: {current}/{total} ({percent}%)")

<<<<<<< HEAD
    def _define_metadata(self):
        """Define corpus metadata and feature descriptions."""
        # Get metadata values
        titles = self.metadata.get("title", [])
        creators = self.metadata.get("creator", [])
        publishers = self.metadata.get("publisher", [])

        title = titles[0] if titles else self.corpus_name
        author = ", ".join(creators) if creators else "Unknown"
        publisher = publishers[0] if publishers else ""

        self.cv.meta(
            name=self.corpus_name,
            version=self.version,
            description=f"{title} - EPUB converted to Text-Fabric",
            author=author,
            publisher=publisher,
            url="",
        )

        # Define node types
        self.cv.meta(
            otype="Node type",
            otext={"fmt:text-orig-full": "{text} "},
        )

        # Define features
        feature_meta = {
            "title": "Title (book or chapter)",
            "creator": "Author/Creator",
            "publisher": "Publisher",
            "language": "Language code",
            "identifier": "Book identifier (ISBN, etc.)",
            "chapter_index": "Chapter index (0-based)",
            "chapter_id": "Chapter ID from EPUB",
            "chapter_name": "Chapter filename",
            "tag": "HTML tag name",
            "class": "CSS class names",
            "id": "HTML id attribute",
            "href": "Link URL",
            "src": "Source URL (img, etc.)",
            "alt": "Alt text",
            "text": "Text content",
            "depth": "Nesting depth in HTML tree",
        }

        for feature, description in feature_meta.items():
            self.cv.meta(**{feature: description})

    def _walk_epub(self):
        """Walk through the EPUB structure and create nodes."""
        # Start book node
        self.cv.node("book")

        # Add book-level metadata
        self._add_book_metadata()

        # Process each chapter/page
        for page in self.pages:
            self._process_chapter(page)

        # End book node
        self.cv.terminate("book")

    def _add_book_metadata(self):
        """Add book-level metadata as features."""
        # Add title
        titles = self.metadata.get("title", [])
        if titles:
            self.cv.feature("title", titles[0])

        # Add creators
        creators = self.metadata.get("creator", [])
        if creators:
            self.cv.feature("creator", ", ".join(creators))

        # Add publisher
        publishers = self.metadata.get("publisher", [])
        if publishers:
            self.cv.feature("publisher", publishers[0])

        # Add language
        languages = self.metadata.get("language", [])
        if languages:
            self.cv.feature("language", languages[0])

        # Add identifier
        identifiers = self.metadata.get("identifier", [])
        if identifiers:
            self.cv.feature("identifier", identifiers[0])

    def _process_chapter(self, page: Dict[str, Any]):
        """Process a single chapter/page."""
        # Start chapter node
        self.cv.node("chapter")

        # Add chapter metadata
        self.cv.feature("chapter_index", str(page["index"]))
        self.cv.feature("chapter_id", page["id"])
        self.cv.feature("chapter_name", page["name"])

        # Parse and process HTML content
        html_content = page["html"]
        if html_content:
            soup = BeautifulSoup(html_content, "html.parser")
            self._walk_element(soup, depth=0)

        # End chapter node
        self.cv.terminate("chapter")

    def _walk_element(self, element: Union[Tag, NavigableString], depth: int = 0):
        """
        Recursively walk through HTML elements.

        Args:
            element: BeautifulSoup Tag or NavigableString
            depth: Current nesting depth
        """
        if isinstance(element, NavigableString):
            # Text content - create word slots
            text = str(element).strip()
            if text and not self._is_whitespace(text):
                self._create_text_slots(text)
            return

        if isinstance(element, Tag):
            # Skip script and style tags (though epub service should have cleaned these)
            if element.name in ["script", "style"]:
                return

            # Handle semantic elements
            if element.name in ["p", "blockquote", "section", "article"]:
                self._process_paragraph(element, depth)
            elif element.name == "a":
                self._process_link(element, depth)
            elif element.name == "table":
                self._process_table(element, depth)
            else:
                # Standard element processing
                self._process_standard_element(element, depth)

    def _process_paragraph(self, element: Tag, depth: int):
        """Process paragraph-like elements."""
        self.cv.node("paragraph")
        self.cv.feature("tag", element.name)
        self.cv.feature("depth", str(depth))
        self._store_attributes(element)

        for child in element.children:
            self._walk_element(child, depth + 1)

        self.cv.terminate("paragraph")

    def _process_link(self, element: Tag, depth: int):
        """Process link elements."""
        self.cv.node("link")
        self.cv.feature("tag", "a")
        self.cv.feature("depth", str(depth))

        href = element.get("href")
        if href:
            self.cv.feature("href", href)

        self._store_attributes(element)

        for child in element.children:
            self._walk_element(child, depth + 1)

        self.cv.terminate("link")

    def _process_table(self, element: Tag, depth: int):
        """Process table elements with row/cell structure."""
        self.cv.node("table")
        self.cv.feature("tag", "table")
        self.cv.feature("depth", str(depth))
        self._store_attributes(element)

        # Process rows
        for row in element.find_all("tr"):
            self.cv.node("row")
            self.cv.feature("tag", "tr")

            # Process cells
            for cell in row.find_all(["td", "th"]):
                self.cv.node("cell")
                self.cv.feature("tag", cell.name)
                self._store_attributes(cell)

                for child in cell.children:
                    self._walk_element(child, depth + 2)

                self.cv.terminate("cell")

            self.cv.terminate("row")

        self.cv.terminate("table")

    def _process_standard_element(self, element: Tag, depth: int):
        """Process standard HTML elements."""
        self.cv.node("element")
        self.cv.feature("tag", element.name)
        self.cv.feature("depth", str(depth))
        self._store_attributes(element)

        for child in element.children:
            self._walk_element(child, depth + 1)

        self.cv.terminate("element")

    def _create_text_slots(self, text: str):
        """
        Create slot nodes for text content.

        Args:
            text: Text string to convert into slots
        """
        text = text.strip()
        if not text:
            return

        if self.tokenize:
            # Split into words
            words = self._tokenize_text(text)
            for word in words:
                if word.strip():
                    self.cv.slot()
                    self.cv.feature("text", word)
                    self.cv.terminate("word")
        else:
            # Use whole text as single slot
            self.cv.slot()
            self.cv.feature("text", text)
            self.cv.terminate("word")

    def _tokenize_text(self, text: str) -> List[str]:
        """
        Tokenize text into words.

        Args:
            text: Text to tokenize

        Returns:
            List of word tokens
        """
        # Simple whitespace tokenization
        return text.split()

    def _store_attributes(self, element: Tag):
        """
        Store HTML attributes as node features.

        Args:
            element: BeautifulSoup Tag
        """
        if not element.attrs:
            return

        for attr_name, attr_value in element.attrs.items():
            # Handle list values (like class)
            if isinstance(attr_value, list):
                attr_value = " ".join(attr_value)

            # Normalize attribute name (replace hyphens with underscores)
            feature_name = attr_name.replace("-", "_")

            # Store as feature
            self.cv.feature(feature_name, str(attr_value))

    @staticmethod
    def _is_whitespace(text: str) -> bool:
        """Check if text is only whitespace."""
        return not text or text.isspace()


def convert_epub_to_tf(
    epub_path: Union[str, Path],
    output_dir: Union[str, Path],
    corpus_name: Optional[str] = None,
    version: str = "1.0",
    tokenize: bool = True,
    on_progress: Optional[Callable[[int, int, float], None]] = None,
=======
    # ── Configuration ─────────────────────────────────────────────────────────

    def _detect_scripture(self) -> bool:
        """Detect scripture-style content by counting verse markers (<sup>N</sup>)."""
        markers = 0
        for page in self.pages:
            soup = BeautifulSoup(page["html"], "html.parser")
            for sup in soup.find_all("sup"):
                if _VERSE_MARKER.match(sup.get_text(strip=True)):
                    markers += 1
                    if markers >= _SCRIPTURE_THRESHOLD:
                        return True
        return False

    def _otext(self) -> dict[str, str]:
        sections = "book,chapter,verse" if self.scripture else "book,chapter"
        return {
            "fmt:text-orig-full": "{text}{after}",
            "sectionTypes": sections,
            "sectionFeatures": sections,
        }

    def _generic_metadata(self) -> dict[str, str]:
        """EPUB Dublin Core metadata, written into every .tf file header."""

        def first(key: str) -> str:
            values = self.metadata.get(key, [])
            return values[0] if values else ""

        generic = {
            "name": self.corpus_name or "",
            "version": self.version,
            "author": ", ".join(self.metadata.get("creator", [])),
            "publisher": first("publisher"),
            "language": first("language"),
            "identifier": first("identifier"),
            "description": first("description"),
            "converter": "corpora-admin-py convert_epub_to_tf",
            "source": self.epub_path,
        }
        return {k: v for k, v in generic.items() if v}

    def _scan_used_features(self) -> set[str]:
        """Determine which features will occur, so metadata matches the output.

        Text-Fabric refuses metadata for features that never receive a value,
        so optional features (links, images, verses) are only declared when
        the scanned pages will actually produce them.
        """
        used = {
            "book", "chapter", "chapter_index", "title",
            "sentence", "clause", "text", "after",
        }
        if self.scripture:
            used.add("verse")
        for page in self.content_pages:
            soup = BeautifulSoup(page["html"], "html.parser")
            if soup.find(True):
                used.add("tag")
            if soup.find("a", href=True):
                used.add("href")
            for img in soup.find_all("img"):
                src = str(img.get("src", ""))
                if src:
                    used.add("src")
                    if Path(src).name in self._asset_map:
                        used.add("asset")
                if img.get("alt"):
                    used.add("alt")
        return used

    def _feature_meta(self, used: set[str]) -> dict[str, dict[str, str]]:
        descriptions = {
            "book": "book name",
            "chapter": "chapter number",
            "verse": "verse number",
            "sentence": "sentence number within book",
            "clause": "clause number within book",
            "chapter_index": "zero-based spine position of the source document",
            "title": "title of book or chapter",
            "text": "word token",
            "after": "punctuation and whitespace after the word",
            "tag": "source HTML tag name",
            "href": "link target URL",
            "src": "image source as referenced in the EPUB",
            "asset": "path of the extracted asset, relative to the dataset",
            "alt": "image alt text",
        }
        return {
            name: {"description": desc}
            for name, desc in descriptions.items()
            if name in used
        }

    # ── Assets ────────────────────────────────────────────────────────────────

    def _extract_assets(self, dataset_dir: Path) -> None:
        """Write EPUB binary assets (images, cover) into {dataset}/assets/."""
        assets = extract_assets(self.epub_path)
        if not assets:
            return

        assets_dir = dataset_dir / "assets"
        for asset in assets:
            # Drop any leading "../" style components from the internal path.
            parts = [p for p in Path(asset["name"]).parts if p not in ("..", "/", ".")]
            if not parts:
                continue
            target = assets_dir.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(asset["content"])
            relative = str(Path("assets").joinpath(*parts))
            self._asset_map[Path(asset["name"]).name] = relative

        print(f"Extracted {len(self._asset_map)} asset(s) to {assets_dir}")

    # ── Walker director ───────────────────────────────────────────────────────

    def _director(self, cv: Any) -> None:
        """Walk the EPUB structure and create TF nodes."""
        self.cv = cv

        pages = self.content_pages

        if self.scripture:
            for page in pages:
                title = self._page_title(page)
                self._book = cv.node("book")
                cv.feature(
                    self._book, book=title, title=title, chapter_index=page["index"]
                )
                self._chapter_num = 0
                self._sentence_num = 0
                self._clause_num = 0
                self._process_page(page)
                self._close_stream_nodes(close_chapter=True)
                cv.terminate(self._book)
                self._book = None
        else:
            self._book = cv.node("book")
            cv.feature(self._book, book=self.corpus_name, title=self.corpus_name)
            for page in pages:
                self._chapter_num += 1
                self._chapter = cv.node("chapter")
                cv.feature(
                    self._chapter,
                    chapter=self._chapter_num,
                    chapter_index=page["index"],
                    title=self._page_title(page),
                )
                self._process_page(page)
                self._close_stream_nodes(close_chapter=True)
            cv.terminate(self._book)
            self._book = None

    @staticmethod
    def _is_navigation(page: dict[str, Any]) -> bool:
        """True for TOC/nav pages: nothing but links and headings, no body text."""
        soup = BeautifulSoup(page["html"], "html.parser")
        if soup.find("img"):
            return False
        for tag in soup.find_all(["a", *_HEADING_TAGS]):
            tag.decompose()
        return not soup.get_text(strip=True)

    def _page_title(self, page: dict[str, Any]) -> str:
        """Title of a spine document: its first heading, else its filename stem."""
        soup = BeautifulSoup(page["html"], "html.parser")
        heading = soup.find(list(_HEADING_TAGS))
        if heading:
            text = heading.get_text(" ", strip=True)
            if text:
                return text
        return Path(page["name"]).stem

    def _process_page(self, page: dict[str, Any]) -> None:
        soup = BeautifulSoup(page["html"], "html.parser")
        for child in soup.children:
            self._walk_element(child)

    def _walk_element(self, element: PageElement) -> None:
        """Recursively walk cleaned HTML, creating nodes and word slots."""
        if isinstance(element, NavigableString):
            self._emit_text(str(element))
            return
        if not isinstance(element, Tag):
            return

        name = element.name

        if name == "sup" and self.scripture:
            marker = element.get_text(strip=True)
            if _VERSE_MARKER.match(marker):
                self._start_verse(int(marker))
                return  # the marker itself is not corpus text
            # non-numeric sup: fall through as inline content

        if name in _HEADING_TAGS:
            self._process_heading(element)
        elif name == "img":
            self._process_image(element)
        elif name == "a":
            self._process_link(element)
        elif name == "table":
            self._process_table(element)
        elif name in _BLOCK_TAGS:
            self._process_paragraph(element)
        else:
            # Inline or unknown container: recurse without creating a node.
            for child in element.children:
                self._walk_element(child)

    # ── Structural elements ───────────────────────────────────────────────────

    def _process_heading(self, element: Tag) -> None:
        text = element.get_text(" ", strip=True)
        if self.scripture:
            match = _TRAILING_INT.search(text)
            if match:
                # Chapter heading ("1", "Chapter 1", "ΚΑΤΑ ΜΑΘΘΑΙΟΝ 1", ...)
                self._start_chapter(int(match.group(1)), from_heading=True)
            elif text and self._book is not None:
                # Book title heading
                self.cv.feature(self._book, book=text, title=text)
            return  # headings are navigation, not corpus text, in scripture mode

        self._process_paragraph(element)

    def _process_paragraph(self, element: Tag) -> None:
        node = self.cv.node("paragraph")
        self.cv.feature(node, tag=element.name)
        for child in element.children:
            self._walk_element(child)
        # Sentences and clauses do not span block boundaries.
        self._close_sentence()
        self.cv.terminate(node)

    def _process_link(self, element: Tag) -> None:
        node = self.cv.node("link")
        self.cv.feature(node, tag="a")
        href = element.get("href")
        if href:
            self.cv.feature(node, href=str(href))
        for child in element.children:
            self._walk_element(child)
        self.cv.terminate(node)

    def _process_table(self, element: Tag) -> None:
        table = self.cv.node("table")
        self.cv.feature(table, tag="table")
        for row in element.find_all("tr"):
            row_node = self.cv.node("row")
            self.cv.feature(row_node, tag="tr")
            for cell in row.find_all(["td", "th"]):
                cell_node = self.cv.node("cell")
                self.cv.feature(cell_node, tag=cell.name)
                for child in cell.children:
                    self._walk_element(child)
                self._close_sentence()
                self.cv.terminate(cell_node)
            self.cv.terminate(row_node)
        self._close_sentence()
        self.cv.terminate(table)

    def _process_image(self, element: Tag) -> None:
        node = self.cv.node("image")
        self.cv.feature(node, tag="img")
        # An image owns one empty slot so it occupies a position in the text.
        slot = self.cv.slot()
        self.cv.feature(slot, text="", after="")

        src = str(element.get("src", ""))
        if src:
            self.cv.feature(node, src=src)
            asset = self._asset_map.get(Path(src).name)
            if asset:
                self.cv.feature(node, asset=asset)
        alt = str(element.get("alt", ""))
        if alt:
            self.cv.feature(node, alt=alt)
        self.cv.terminate(node)

    # ── Scripture structure ───────────────────────────────────────────────────

    def _start_chapter(self, number: int | None, from_heading: bool = False) -> None:
        self._close_stream_nodes(close_chapter=True)
        self._chapter_num = number if number is not None else self._chapter_num + 1
        self._chapter = self.cv.node("chapter")
        self.cv.feature(self._chapter, chapter=self._chapter_num)
        self._chapter_from_heading = from_heading
        self._verse_num = 0

    def _start_verse(self, number: int) -> None:
        self._close_verse()
        if self._chapter is None:
            self._start_chapter(None)
        elif number == 1 and self._verse_num >= 1 and not self._chapter_from_heading:
            # Verse numbering restarted without a chapter heading: new chapter.
            self._start_chapter(None)
        self._verse_num = number
        self._verse = self.cv.node("verse")
        self.cv.feature(self._verse, verse=number)

    # ── Words, sentences, clauses ─────────────────────────────────────────────

    def _emit_text(self, text: str) -> None:
        if not text or text.isspace():
            return
        if self.tokenize:
            for word, after in self._tokenize_text(text):
                self._emit_word(word, after)
        else:
            self._emit_word(text.strip(), " ")

    def _tokenize_text(self, text: str) -> list[tuple[str, str]]:
        """Split text into (word, after) pairs; trailing punctuation goes to after."""
        tokens = []
        for raw in text.split():
            word = raw.rstrip(_STRIP_PUNCT)
            if not word:
                word = raw  # token is pure punctuation, keep it as text
            after = raw[len(word):] + " "
            tokens.append((word, after))
        return tokens

    def _emit_word(self, word: str, after: str) -> None:
        cv = self.cv
        if self.scripture and self._chapter is None:
            self._start_chapter(None)
        if self._sentence is None:
            self._sentence_num += 1
            self._sentence = cv.node("sentence")
            cv.feature(self._sentence, sentence=self._sentence_num)
        if self._clause is None:
            self._clause_num += 1
            self._clause = cv.node("clause")
            cv.feature(self._clause, clause=self._clause_num)

        slot = cv.slot()
        cv.feature(slot, text=word, after=after)

        if any(c in _SENTENCE_END for c in after):
            self._close_sentence()
        elif any(c in _CLAUSE_END for c in after):
            self._close_clause()

    # ── Node lifecycle helpers ────────────────────────────────────────────────

    def _close_clause(self) -> None:
        if self._clause is not None:
            self.cv.terminate(self._clause)
            self._clause = None

    def _close_sentence(self) -> None:
        self._close_clause()
        if self._sentence is not None:
            self.cv.terminate(self._sentence)
            self._sentence = None

    def _close_verse(self) -> None:
        if self._verse is not None:
            self.cv.terminate(self._verse)
            self._verse = None

    def _close_stream_nodes(self, close_chapter: bool = False) -> None:
        """Close sentence/clause/verse (and optionally chapter) stream nodes."""
        self._close_sentence()
        self._close_verse()
        if close_chapter and self._chapter is not None:
            self.cv.terminate(self._chapter)
            self._chapter = None


def convert_epub_to_tf(
    epub_path: str | Path,
    output_dir: str | Path,
    corpus_name: str | None = None,
    version: str = "1.0",
    tokenize: bool = True,
    on_progress: Callable[[int, int, float], None] | None = None,
>>>>>>> origin/dev
) -> Path:
    """
    Convenience function to convert EPUB to Text-Fabric.

    Args:
        epub_path: Path or URL to EPUB file
        output_dir: Directory where TF files will be created
        corpus_name: Name of the corpus (defaults to EPUB title)
        version: Version string
        tokenize: If True, split text into word slots
        on_progress: Optional progress callback(current, total, percent)

    Returns:
<<<<<<< HEAD
        Path to generated TF directory

    Example:
        >>> tf_path = convert_epub_to_tf(
        ...     epub_path="book.epub",
        ...     output_dir="tf_output/",
        ...     corpus_name="MyBook"
        ... )
        >>> print(f"TF dataset created at: {tf_path}")

        >>> # Load and query
        >>> import cfabric
        >>> CF = cfabric.Fabric(tf_path)
        >>> api = CF.loadAll()
        >>> api.makeAvailableIn(globals())
        >>>
        >>> # Find all chapter titles
        >>> results = S.search('chapter')
        >>> for chapter in results:
        ...     title = F.chapter_name.v(chapter)
        ...     print(f"Chapter: {title}")
=======
        Path to generated TF dataset directory
        ({output_dir}/{corpus_name}/tf/{version})

    Example:
        >>> tf_path = convert_epub_to_tf(
        ...     epub_path="bible.epub",
        ...     output_dir="tf_output/",
        ...     corpus_name="SBL",
        ... )

        >>> # Load and query
        >>> import cfabric
        >>> CF = cfabric.Fabric(locations=str(tf_path))
        >>> api = CF.loadAll()
        >>>
        >>> # Read John 3:16 (scripture mode)
        >>> node = api.T.nodeFromSection(("John", 3, 16))
        >>> print(api.T.text(node))
>>>>>>> origin/dev
    """
    converter = EPUBToTFConverter(
        epub_path=epub_path,
        output_dir=output_dir,
        corpus_name=corpus_name,
        version=version,
        tokenize=tokenize,
        on_progress=on_progress,
    )

    return converter.convert()


# Example usage
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
<<<<<<< HEAD
        print("Usage: python epub_to_tf.py <epub_file> [output_dir] [corpus_name]")
        print("\nExample:")
        print("  python epub_to_tf.py book.epub tf_output/ MyBook")
        print("  python epub_to_tf.py https://example.com/book.epub tf_output/")
        sys.exit(1)

    epub_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "tf_output"
    corpus_name = sys.argv[3] if len(sys.argv) > 3 else None

    print(f"Converting EPUB to Text-Fabric format...")
    print(f"Input: {epub_path}")
    print(f"Output directory: {output_dir}")
    if corpus_name:
        print(f"Corpus name: {corpus_name}")
    print()

    try:
        tf_path = convert_epub_to_tf(
            epub_path=epub_path,
            output_dir=output_dir,
            corpus_name=corpus_name,
        )

        print("\n✅ Success!")
        print(f"TF files created at: {tf_path}")
        print("\nYou can now load this corpus with Context-Fabric:")
        print(f"  import cfabric")
        print(f"  CF = cfabric.Fabric('{tf_path}')")
        print(f"  api = CF.loadAll()")
        print(f"  api.makeAvailableIn(globals())")
        print("\nExample queries:")
        print("  # Find all chapters")
        print("  chapters = S.search('chapter')")
        print("  # Find all paragraphs")
        print("  paragraphs = S.search('paragraph')")
        print("  # Find all links")
        print("  links = S.search('link')")

    except Exception as e:
        print(f"\n❌ Error: {e}")
=======
        print("Usage: python -m admin.utils.convert_epub_to_tf <epub_file> [output_dir] [corpus_name]")
        sys.exit(1)

    epub_arg = sys.argv[1]
    output_arg = sys.argv[2] if len(sys.argv) > 2 else "tf_output"
    name_arg = sys.argv[3] if len(sys.argv) > 3 else None

    try:
        result_path = convert_epub_to_tf(
            epub_path=epub_arg,
            output_dir=output_arg,
            corpus_name=name_arg,
        )
        print(f"\nTF files created at: {result_path}")
    except Exception as exc:
        print(f"\nError: {exc}")
>>>>>>> origin/dev
        import traceback

        traceback.print_exc()
        sys.exit(1)
