"""
EPUB to Text-Fabric Converter

Converts EPUB ebook files into Text-Fabric datasets using the epub service
for parsing and the tf.convert.walker library for TF generation.

Features:
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

Usage:
    from app.utils.epub_to_tf import convert_epub_to_tf

    tf_path = convert_epub_to_tf(
        epub_path="book.epub",
        output_dir="tf_output/",
        corpus_name="MyBook"
    )
"""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from bs4 import BeautifulSoup, NavigableString, Tag
from tf.convert.walker import CV

from exegia.services.epub import extract_pages, get_metadata


class EPUBToTFConverter:
    """
    Converts EPUB files to Text-Fabric format.

    Uses the epub service to parse EPUB files and extracts clean HTML,
    then converts to TF using the walker API.
    """

    def __init__(
        self,
        epub_path: Union[str, Path],
        output_dir: Union[str, Path],
        corpus_name: Optional[str] = None,
        version: str = "1.0",
        tokenize: bool = True,
        on_progress: Optional[Callable[[int, int, float], None]] = None,
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

        # Converter instance (initialized in convert())
        self.cv = None

        # EPUB metadata
        self.metadata = {}
        self.pages = []

    def convert(self) -> Path:
        """
        Convert EPUB to Text-Fabric format.

        Returns:
            Path to the generated TF directory
        """
        print(f"Loading EPUB: {self.epub_path}")

        # Extract metadata
        self.metadata = get_metadata(self.epub_path)

        # Use title as corpus name if not provided
        if not self.corpus_name:
            titles = self.metadata.get("title", [])
            self.corpus_name = titles[0] if titles else "EPUBCorpus"

        print(f"Title: {self.corpus_name}")
        print(f"Total pages: {self.metadata.get('total_pages', 0)}")

        # Extract pages
        print("Extracting pages...")
        self.pages = extract_pages(
            self.epub_path,
            on_progress=self._handle_extraction_progress,
        )

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

    def _handle_extraction_progress(self, current: int, total: int, percent: float):
        """Handle progress callback from EPUB extraction."""
        if self.on_progress:
            self.on_progress(current, total, percent)
        else:
            print(f"  Extracting: {current}/{total} ({percent}%)")

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
        import traceback

        traceback.print_exc()
        sys.exit(1)
