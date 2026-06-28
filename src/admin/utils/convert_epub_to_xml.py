"""
EPUB to TEI XML Converter

This module converts EPUB files to TEI (Text Encoding Initiative) XML format.
TEI XML is a standard for encoding texts in digital form, particularly in the humanities.

Usage:
    from app.utils.convert_epub_to_xml import EpubToTeiConverter

    converter = EpubToTeiConverter('input.epub')
    tei_xml = converter.convert()

    # Save to file
    with open('output.xml', 'w', encoding='utf-8') as f:
        f.write(tei_xml)

Dependencies:
    pip install ebooklib lxml beautifulsoup4
"""

import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

try:
    import ebooklib
    from ebooklib import epub

    EBOOKLIB_AVAILABLE = True
except ImportError:
    EBOOKLIB_AVAILABLE = False

from bs4 import BeautifulSoup
from lxml import etree


class EpubToTeiConverter:
    """
    Converts EPUB files to TEI XML format following TEI P5 guidelines.

    TEI XML structure:
    - <teiHeader>: Contains metadata about the text
    - <text>: Contains the actual text content
      - <front>: Front matter (preface, dedication, etc.)
      - <body>: Main text body
      - <back>: Back matter (appendices, notes, etc.)
    """

    # TEI namespace
    TEI_NS = "http://www.tei-c.org/ns/1.0"
    XML_NS = "http://www.w3.org/XML/1998/namespace"

    def __init__(self, epub_path: str):
        """
        Initialize the converter with an EPUB file.

        Args:
            epub_path: Path to the EPUB file
        """
        self.epub_path = Path(epub_path)
        if not self.epub_path.exists():
            raise FileNotFoundError(f"EPUB file not found: {epub_path}")

        self.book = None
        self.metadata = {}

    def convert(self, output_path: Optional[str] = None) -> str:
        """
        Convert EPUB to TEI XML.

        Args:
            output_path: Optional path to save the TEI XML file

        Returns:
            TEI XML string
        """
        if not EBOOKLIB_AVAILABLE:
            raise ImportError(
                "ebooklib is required for EPUB conversion. "
                "Install with: pip install ebooklib"
            )

        # Load EPUB
        self.book = epub.read_epub(str(self.epub_path))

        # Extract metadata
        self._extract_metadata()

        # Build TEI structure
        tei_root = self._build_tei_structure()

        # Convert to string with pretty formatting
        tei_xml = self._serialize_tei(tei_root)

        # Save to file if requested
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(tei_xml)

        return tei_xml

    def _extract_metadata(self):
        """Extract metadata from EPUB."""
        # Title
        title = self.book.get_metadata("DC", "title")
        self.metadata["title"] = title[0][0] if title else "Unknown Title"

        # Author(s)
        authors = self.book.get_metadata("DC", "creator")
        self.metadata["authors"] = (
            [author[0] for author in authors] if authors else ["Unknown Author"]
        )

        # Publisher
        publisher = self.book.get_metadata("DC", "publisher")
        self.metadata["publisher"] = publisher[0][0] if publisher else None

        # Date
        date = self.book.get_metadata("DC", "date")
        self.metadata["date"] = date[0][0] if date else None

        # Language
        language = self.book.get_metadata("DC", "language")
        self.metadata["language"] = language[0][0] if language else "en"

        # Description
        description = self.book.get_metadata("DC", "description")
        self.metadata["description"] = description[0][0] if description else None

        # Subject(s)
        subjects = self.book.get_metadata("DC", "subject")
        self.metadata["subjects"] = (
            [subject[0] for subject in subjects] if subjects else []
        )

        # Rights
        rights = self.book.get_metadata("DC", "rights")
        self.metadata["rights"] = rights[0][0] if rights else None

        # Identifier (ISBN, DOI, etc.)
        identifier = self.book.get_metadata("DC", "identifier")
        self.metadata["identifier"] = identifier[0][0] if identifier else None

    def _build_tei_structure(self) -> etree.Element:
        """
        Build the TEI XML structure.

        Returns:
            Root TEI element
        """
        # Create root TEI element with namespace
        nsmap = {None: self.TEI_NS, "xml": self.XML_NS}
        tei = etree.Element(f"{{{self.TEI_NS}}}TEI", nsmap=nsmap)
        tei.set(f"{{{self.XML_NS}}}lang", self.metadata.get("language", "en"))

        # Add processing instruction for TEI extension (following third party conventions)
        pi = etree.ProcessingInstruction(
            "tei-ext",
            f'name="epub-conversion" version="1.0" date="{datetime.now().isoformat()}"',
        )
        tei.addprevious(pi)

        # Build header
        tei_header = self._build_header()
        tei.append(tei_header)

        # Build text
        text = self._build_text()
        tei.append(text)

        return tei

    def _build_header(self) -> etree.Element:
        """
        Build the TEI header with metadata.

        Returns:
            teiHeader element
        """
        header = etree.Element(f"{{{self.TEI_NS}}}teiHeader")

        # File description
        file_desc = etree.SubElement(header, f"{{{self.TEI_NS}}}fileDesc")

        # Title statement
        title_stmt = etree.SubElement(file_desc, f"{{{self.TEI_NS}}}titleStmt")
        title_el = etree.SubElement(title_stmt, f"{{{self.TEI_NS}}}title")
        title_el.text = self.metadata["title"]

        # Authors
        for author in self.metadata["authors"]:
            author_el = etree.SubElement(title_stmt, f"{{{self.TEI_NS}}}author")
            author_el.text = author

        # Publication statement
        pub_stmt = etree.SubElement(file_desc, f"{{{self.TEI_NS}}}publicationStmt")

        if self.metadata.get("publisher"):
            publisher_el = etree.SubElement(pub_stmt, f"{{{self.TEI_NS}}}publisher")
            publisher_el.text = self.metadata["publisher"]

        if self.metadata.get("date"):
            date_el = etree.SubElement(pub_stmt, f"{{{self.TEI_NS}}}date")
            date_el.text = self.metadata["date"]

        if self.metadata.get("identifier"):
            idno_el = etree.SubElement(pub_stmt, f"{{{self.TEI_NS}}}idno")
            idno_el.text = self.metadata["identifier"]

        if not any([self.metadata.get("publisher"), self.metadata.get("date")]):
            p = etree.SubElement(pub_stmt, f"{{{self.TEI_NS}}}p")
            p.text = "Publication details unknown"

        # Source description
        source_desc = etree.SubElement(file_desc, f"{{{self.TEI_NS}}}sourceDesc")
        p = etree.SubElement(source_desc, f"{{{self.TEI_NS}}}p")
        p.text = f"Converted from EPUB: {self.epub_path.name}"

        # Encoding description (optional but recommended)
        encoding_desc = etree.SubElement(header, f"{{{self.TEI_NS}}}encodingDesc")
        proj_desc = etree.SubElement(encoding_desc, f"{{{self.TEI_NS}}}projectDesc")
        p = etree.SubElement(proj_desc, f"{{{self.TEI_NS}}}p")
        p.text = "Automatically converted from EPUB format to TEI XML"

        # Profile description (for subjects, language, etc.)
        if self.metadata.get("subjects") or self.metadata.get("description"):
            profile_desc = etree.SubElement(header, f"{{{self.TEI_NS}}}profileDesc")

            if self.metadata.get("description"):
                abstract = etree.SubElement(profile_desc, f"{{{self.TEI_NS}}}abstract")
                p = etree.SubElement(abstract, f"{{{self.TEI_NS}}}p")
                p.text = self.metadata["description"]

            if self.metadata.get("subjects"):
                text_class = etree.SubElement(
                    profile_desc, f"{{{self.TEI_NS}}}textClass"
                )
                keywords = etree.SubElement(text_class, f"{{{self.TEI_NS}}}keywords")
                for subject in self.metadata["subjects"]:
                    term = etree.SubElement(keywords, f"{{{self.TEI_NS}}}term")
                    term.text = subject

        return header

    def _build_text(self) -> etree.Element:
        """
        Build the text element with content from EPUB.

        Returns:
            text element
        """
        text = etree.Element(f"{{{self.TEI_NS}}}text")

        # Create body
        body = etree.SubElement(text, f"{{{self.TEI_NS}}}body")

        # Process all HTML/XHTML documents
        for item in self.book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                self._process_document(body, item)

        return text

    def _process_document(self, parent: etree.Element, item: epub.EpubItem):
        """
        Process an EPUB document item and add to TEI structure.

        Args:
            parent: Parent TEI element to append to
            item: EPUB document item
        """
        # Parse HTML content
        content = item.get_content()
        soup = BeautifulSoup(content, "html.parser")

        # Remove script and style tags
        for tag in soup(["script", "style"]):
            tag.decompose()

        # Create a division for this document
        div = etree.SubElement(parent, f"{{{self.TEI_NS}}}div")

        # Try to get title from first heading
        heading = soup.find(["h1", "h2", "h3", "h4", "h5", "h6"])
        if heading:
            head_el = etree.SubElement(div, f"{{{self.TEI_NS}}}head")
            head_el.text = heading.get_text(strip=True)
            heading.decompose()  # Remove from soup after extracting

        # Convert HTML structure to TEI
        self._convert_html_to_tei(soup.body if soup.body else soup, div)

    def _convert_html_to_tei(self, html_element, tei_parent: etree.Element):
        """
        Recursively convert HTML elements to TEI elements.

        Args:
            html_element: BeautifulSoup HTML element
            tei_parent: Parent TEI element
        """
        if html_element is None:
            return

        for element in html_element.children:
            if isinstance(element, str):
                # Text node
                text = element.strip()
                if text:
                    if len(tei_parent):
                        # Append to tail of last child
                        if tei_parent[-1].tail:
                            tei_parent[-1].tail += text
                        else:
                            tei_parent[-1].tail = text
                    else:
                        # Append to text of parent
                        if tei_parent.text:
                            tei_parent.text += text
                        else:
                            tei_parent.text = text
                continue

            # Map HTML tags to TEI equivalents
            tag_name = element.name.lower()

            if tag_name in ["p"]:
                p = etree.SubElement(tei_parent, f"{{{self.TEI_NS}}}p")
                self._convert_html_to_tei(element, p)

            elif tag_name in ["div", "section", "article"]:
                div = etree.SubElement(tei_parent, f"{{{self.TEI_NS}}}div")
                self._convert_html_to_tei(element, div)

            elif tag_name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                head = etree.SubElement(tei_parent, f"{{{self.TEI_NS}}}head")
                head.text = element.get_text(strip=True)

            elif tag_name in ["em", "i"]:
                emph = etree.SubElement(tei_parent, f"{{{self.TEI_NS}}}emph")
                self._convert_html_to_tei(element, emph)

            elif tag_name in ["strong", "b"]:
                hi = etree.SubElement(tei_parent, f"{{{self.TEI_NS}}}hi")
                hi.set("rend", "bold")
                self._convert_html_to_tei(element, hi)

            elif tag_name == "a":
                ref = etree.SubElement(tei_parent, f"{{{self.TEI_NS}}}ref")
                href = element.get("href")
                if href:
                    ref.set("target", href)
                self._convert_html_to_tei(element, ref)

            elif tag_name in ["ul", "ol"]:
                list_el = etree.SubElement(tei_parent, f"{{{self.TEI_NS}}}list")
                list_el.set("type", "ordered" if tag_name == "ol" else "unordered")
                self._convert_html_to_tei(element, list_el)

            elif tag_name == "li":
                item = etree.SubElement(tei_parent, f"{{{self.TEI_NS}}}item")
                self._convert_html_to_tei(element, item)

            elif tag_name == "blockquote":
                quote = etree.SubElement(tei_parent, f"{{{self.TEI_NS}}}quote")
                self._convert_html_to_tei(element, quote)

            elif tag_name in ["pre", "code"]:
                # Code blocks
                ab = etree.SubElement(tei_parent, f"{{{self.TEI_NS}}}ab")
                ab.set("type", "code")
                ab.text = element.get_text()

            elif tag_name == "br":
                lb = etree.SubElement(tei_parent, f"{{{self.TEI_NS}}}lb")

            elif tag_name == "hr":
                milestone = etree.SubElement(tei_parent, f"{{{self.TEI_NS}}}milestone")
                milestone.set("unit", "section")

            elif tag_name in ["table"]:
                table = etree.SubElement(tei_parent, f"{{{self.TEI_NS}}}table")
                self._convert_html_to_tei(element, table)

            elif tag_name == "tr":
                row = etree.SubElement(tei_parent, f"{{{self.TEI_NS}}}row")
                self._convert_html_to_tei(element, row)

            elif tag_name in ["td", "th"]:
                cell = etree.SubElement(tei_parent, f"{{{self.TEI_NS}}}cell")
                if tag_name == "th":
                    cell.set("role", "label")
                self._convert_html_to_tei(element, cell)

            else:
                # For unrecognized tags, just process children
                self._convert_html_to_tei(element, tei_parent)

    def _serialize_tei(self, tei_root: etree.Element) -> str:
        """
        Serialize TEI element to formatted XML string.

        Args:
            tei_root: Root TEI element

        Returns:
            Formatted XML string
        """
        # Add XML declaration
        xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'

        # Serialize with pretty printing
        tei_string = etree.tostring(
            tei_root, pretty_print=True, encoding="unicode", xml_declaration=False
        )

        return xml_declaration + tei_string


def convert_epub_to_tei(epub_path: str, output_path: Optional[str] = None) -> str:
    """
    Convenience function to convert EPUB to TEI XML.

    Args:
        epub_path: Path to EPUB file
        output_path: Optional path to save TEI XML

    Returns:
        TEI XML string

    Example:
        >>> tei_xml = convert_epub_to_tei('mybook.epub', 'mybook.xml')
    """
    converter = EpubToTeiConverter(epub_path)
    return converter.convert(output_path)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python convert_epub_to_xml.py <epub_file> [output_file]")
        sys.exit(1)

    epub_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    if not output_file:
        # Generate output filename
        output_file = Path(epub_file).with_suffix(".xml")

    print(f"Converting {epub_file} to TEI XML...")
    tei_xml = convert_epub_to_tei(epub_file, str(output_file))
    print(f"TEI XML saved to {output_file}")
    print(f"Output length: {len(tei_xml)} characters")
