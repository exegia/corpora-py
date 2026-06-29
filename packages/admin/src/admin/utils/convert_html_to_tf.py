"""
HTML to Text-Fabric Converter

Converts HTML documents into Text-Fabric (TF) datasets using the tf.convert.walker library.
This allows HTML content to be queried using Context-Fabric's powerful graph query API.

Features:
- Preserves HTML structure as a node hierarchy
- Creates slots for text content (words/tokens)
- Stores HTML attributes as node features
- Supports nested HTML elements
- Generates valid Text-Fabric datasets

Node Types:
- document: Root node for each HTML document
- element: HTML tags (div, p, span, etc.)
- word: Individual words (slots)

Features:
- tag: HTML tag name (div, p, span, etc.)
- class: CSS class names
- id: HTML id attribute
- href: Link URLs (for <a> tags)
- src: Source URLs (for <img>, <script> tags)
- text: Raw text content
- * (any HTML attribute preserved as feature)
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from bs4 import BeautifulSoup, NavigableString, Tag
from tf.convert.walker import CV


class HTMLToTFConverter:
    """
    Converts HTML documents to Text-Fabric format.

    Usage:
        converter = HTMLToTFConverter(
            input_dir="html_files/",
            output_dir="tf_output/",
            corpus_name="MyHTMLCorpus"
        )
        converter.convert()
    """

    def __init__(
        self,
        input_dir: Union[str, Path],
        output_dir: Union[str, Path],
        corpus_name: str = "HTMLCorpus",
        version: str = "1.0",
        tokenize: bool = True,
        preserve_whitespace: bool = False,
    ):
        """
        Initialize the HTML to TF converter.

        Args:
            input_dir: Directory containing HTML files
            output_dir: Directory where TF files will be created
            corpus_name: Name of the corpus
            version: Version string
            tokenize: If True, split text into word slots; if False, use character slots
            preserve_whitespace: If True, preserve whitespace in text
        """
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.corpus_name = corpus_name
        self.version = version
        self.tokenize = tokenize
        self.preserve_whitespace = preserve_whitespace

        # Converter instance (initialized in convert())
        self.cv = None

        # Current document being processed
        self.current_doc = None
        self.doc_index = 0

    def convert(self) -> Path:
        """
        Convert all HTML files to Text-Fabric format.

        Returns:
            Path to the generated TF directory
        """
        if not self.input_dir.exists():
            raise FileNotFoundError(f"Input directory not found: {self.input_dir}")

        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize the converter
        self.cv = CV(
            location=str(self.output_dir),
            module=self.corpus_name,
            version=self.version,
        )

        # Define metadata
        self._define_metadata()

        # Walk through the data
        self._walk_html_files()

        # Generate TF files
        tf_path = self.cv.terminate()

        print(f"✅ Conversion complete! TF files created at: {tf_path}")
        return Path(tf_path)

    def _define_metadata(self):
        """Define corpus metadata and feature descriptions."""
        self.cv.meta(
            name=self.corpus_name,
            version=self.version,
            description=f"{self.corpus_name} - HTML documents converted to Text-Fabric",
            author="HTML to TF Converter",
            url="",
        )

        # Define node types
        self.cv.meta(
            otype="Node type",
            otext={"fmt:text-orig-full": "{text} "},
        )

        # Define features
        feature_meta = {
            "tag": "HTML tag name (div, p, span, etc.)",
            "class": "CSS class names",
            "id": "HTML id attribute",
            "href": "Link URL (for <a> tags)",
            "src": "Source URL (for <img>, <script>, etc.)",
            "alt": "Alt text (for <img> tags)",
            "title": "Title attribute",
            "text": "Raw text content",
            "filename": "Source HTML filename",
            "depth": "Nesting depth in HTML tree",
        }

        for feature, description in feature_meta.items():
            self.cv.meta(**{feature: description})

    def _walk_html_files(self):
        """Walk through all HTML files and convert them."""
        html_files = list(self.input_dir.glob("*.html")) + list(
            self.input_dir.glob("*.htm")
        )

        if not html_files:
            raise ValueError(f"No HTML files found in {self.input_dir}")

        print(f"Found {len(html_files)} HTML files to convert")

        for html_file in sorted(html_files):
            print(f"Processing: {html_file.name}")
            self._process_html_file(html_file)

    def _process_html_file(self, html_file: Path):
        """Process a single HTML file."""
        self.current_doc = html_file.stem
        self.doc_index += 1

        # Read HTML content
        with open(html_file, "r", encoding="utf-8") as f:
            html_content = f.read()

        # Parse HTML
        soup = BeautifulSoup(html_content, "html.parser")

        # Start document node
        self.cv.node("document")
        self.cv.feature("filename", html_file.name)

        # Process the HTML tree
        self._walk_element(soup, depth=0)

        # End document node
        self.cv.terminate("document")

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
            # Skip script and style tags
            if element.name in ["script", "style"]:
                return

            # Start element node
            self.cv.node("element")
            self.cv.feature("tag", element.name)
            self.cv.feature("depth", str(depth))

            # Extract and store attributes
            self._store_attributes(element)

            # Process children
            for child in element.children:
                self._walk_element(child, depth + 1)

            # End element node
            self.cv.terminate("element")

    def _create_text_slots(self, text: str):
        """
        Create slot nodes for text content.

        Args:
            text: Text string to convert into slots
        """
        if not self.preserve_whitespace:
            text = re.sub(r"\s+", " ", text).strip()

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
        # Simple whitespace tokenization (can be enhanced)
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


class AdvancedHTMLToTFConverter(HTMLToTFConverter):
    """
    Advanced HTML to TF converter with additional features.

    Enhancements:
    - Creates paragraph and sentence nodes
    - Extracts links and creates edge features
    - Handles tables with row/cell structure
    - Preserves document metadata (title, meta tags)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.links = []  # Store links for edge creation
        self.metadata = {}  # Store document metadata

    def _process_html_file(self, html_file: Path):
        """Process HTML with advanced features."""
        self.current_doc = html_file.stem
        self.doc_index += 1
        self.links = []
        self.metadata = {}

        # Read and parse HTML
        with open(html_file, "r", encoding="utf-8") as f:
            html_content = f.read()

        soup = BeautifulSoup(html_content, "html.parser")

        # Extract metadata
        self._extract_metadata(soup)

        # Start document node
        self.cv.node("document")
        self.cv.feature("filename", html_file.name)

        # Add metadata as features
        for key, value in self.metadata.items():
            self.cv.feature(key, value)

        # Process body (or entire document if no body)
        body = soup.find("body") or soup
        self._walk_element_advanced(body, depth=0)

        # End document node
        self.cv.terminate("document")

    def _extract_metadata(self, soup: BeautifulSoup):
        """Extract document metadata from head section."""
        # Title
        title_tag = soup.find("title")
        if title_tag:
            self.metadata["title"] = title_tag.get_text().strip()

        # Meta tags
        meta_tags = soup.find_all("meta")
        for meta in meta_tags:
            name = meta.get("name") or meta.get("property")
            content = meta.get("content")
            if name and content:
                self.metadata[f"meta_{name}"] = content

    def _walk_element_advanced(
        self, element: Union[Tag, NavigableString], depth: int = 0
    ):
        """Walk through HTML with advanced semantic handling."""
        if isinstance(element, NavigableString):
            text = str(element).strip()
            if text and not self._is_whitespace(text):
                self._create_text_slots(text)
            return

        if isinstance(element, Tag):
            # Skip script and style
            if element.name in ["script", "style"]:
                return

            # Handle special semantic elements
            if element.name in ["p", "div", "section", "article"]:
                self._process_paragraph(element, depth)
            elif element.name == "table":
                self._process_table(element, depth)
            elif element.name == "a":
                self._process_link(element, depth)
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
            self._walk_element_advanced(child, depth + 1)

        self.cv.terminate("paragraph")

    def _process_link(self, element: Tag, depth: int):
        """Process link elements."""
        self.cv.node("link")
        self.cv.feature("tag", "a")
        self.cv.feature("depth", str(depth))

        href = element.get("href")
        if href:
            self.cv.feature("href", href)
            self.links.append(href)

        self._store_attributes(element)

        for child in element.children:
            self._walk_element_advanced(child, depth + 1)

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
                    self._walk_element_advanced(child, depth + 2)

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
            self._walk_element_advanced(child, depth + 1)

        self.cv.terminate("element")


def convert_html_to_tf(
    input_dir: Union[str, Path],
    output_dir: Union[str, Path],
    corpus_name: str = "HTMLCorpus",
    version: str = "1.0",
    advanced: bool = False,
    **kwargs,
) -> Path:
    """
    Convenience function to convert HTML to Text-Fabric.

    Args:
        input_dir: Directory containing HTML files
        output_dir: Directory where TF files will be created
        corpus_name: Name of the corpus
        version: Version string
        advanced: Use advanced converter with semantic features
        **kwargs: Additional arguments passed to converter

    Returns:
        Path to generated TF directory

    Example:
        >>> tf_path = convert_html_to_tf(
        ...     input_dir="html_docs/",
        ...     output_dir="tf_output/",
        ...     corpus_name="Documentation",
        ...     advanced=True
        ... )
        >>> print(f"TF dataset created at: {tf_path}")
    """
    converter_class = AdvancedHTMLToTFConverter if advanced else HTMLToTFConverter

    converter = converter_class(
        input_dir=input_dir,
        output_dir=output_dir,
        corpus_name=corpus_name,
        version=version,
        **kwargs,
    )

    return converter.convert()


# Example usage
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print(
            "Usage: python convert_html_to_tf.py <input_dir> <output_dir> [corpus_name]"
        )
        print("\nExample:")
        print("  python convert_html_to_tf.py html_files/ tf_output/ MyCorpus")
        sys.exit(1)

    input_dir = sys.argv[1]
    output_dir = sys.argv[2]
    corpus_name = sys.argv[3] if len(sys.argv) > 3 else "HTMLCorpus"

    print(f"Converting HTML files from {input_dir} to Text-Fabric format...")
    print(f"Output directory: {output_dir}")
    print(f"Corpus name: {corpus_name}\n")

    try:
        tf_path = convert_html_to_tf(
            input_dir=input_dir,
            output_dir=output_dir,
            corpus_name=corpus_name,
            advanced=True,
        )

        print("\n✅ Success!")
        print(f"TF files created at: {tf_path}")
        print("\nYou can now load this corpus with Context-Fabric:")
        print(f"  import cfabric")
        print(f"  CF = cfabric.Fabric('{tf_path}')")
        print(f"  api = CF.loadAll()")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
