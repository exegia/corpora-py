"""
HTML parser — converts an HTML document into the shared Document/Unit schema.

`element_to_unit()` and `unit_attrs()` are also imported by `_epub.py`,
`_xml.py` and `_tei.py`: EPUB chapters, generic XML, and TEI are all markup
trees, so they share the same recursive walker instead of each parser
re-implementing it.
"""

from collections.abc import Iterator

from bs4 import BeautifulSoup, NavigableString, Tag

from .schema import DocumentMetadata, Parser, SourceFormat, Unit, read_source_bytes, tokenize

# Tags whose subtree carries no document structure worth preserving. This is
# scoped to tags that can appear *inside* <body> with no useful content —
# HTML's own <head> lives outside <body> so it never reaches this walker, and
# other formats (e.g. TEI's <head>, a heading) reuse the tag name for
# something meaningful, so it must not be dropped here.
SKIP_TAGS = {"script", "style", "noscript", "svg", "math"}

# Free-form `Unit.type` used for a run of text sitting alongside element
# siblings (mixed content), e.g. the "and " in "<p>Hello <b>world</b> and me</p>".
TEXT_UNIT_TYPE = "text"


def attr_str(tag: Tag, name: str) -> str | None:
    """Read a tag attribute as a plain string, even if bs4 parsed it as a
    multi-valued attribute list (e.g. `class`)."""
    value = tag.get(name)
    if isinstance(value, list):
        return " ".join(value) if value else None
    return value


def unit_attrs(tag: Tag) -> dict[str, str]:
    """Flatten a BeautifulSoup tag's attributes into `Unit.attrs`."""
    attrs: dict[str, str] = {}
    for name, value in tag.attrs.items():
        attrs[name] = " ".join(value) if isinstance(value, list) else str(value)
    return attrs


def element_to_unit(tag: Tag) -> Unit:
    """
    Recursively convert a markup `Tag` into a `Unit`.

    A tag with only text content becomes a leaf `Unit` with `tokens`. A tag
    with element children becomes a `Unit` whose `children` interleave
    nested element `Unit`s with `TEXT_UNIT_TYPE` `Unit`s for the text runs
    between them, preserving document order.
    """
    if all(isinstance(node, NavigableString) for node in tag.contents):
        return Unit(type=tag.name, attrs=unit_attrs(tag), tokens=tokenize(tag.get_text()))

    children: list[Unit] = []
    for node in tag.contents:
        if isinstance(node, Tag):
            if node.name in SKIP_TAGS:
                continue
            children.append(element_to_unit(node))
        elif isinstance(node, NavigableString) and node.strip():
            children.append(Unit(type=TEXT_UNIT_TYPE, tokens=tokenize(str(node))))

    return Unit(type=tag.name, attrs=unit_attrs(tag), children=children)


def top_level_units(container: Tag) -> list[Unit]:
    """Convert `container`'s direct element children into `Unit`s."""
    return [
        element_to_unit(child)
        for child in container.contents
        if isinstance(child, Tag) and child.name not in SKIP_TAGS
    ]


def _load(source: str) -> BeautifulSoup:
    return BeautifulSoup(read_source_bytes(source), "html.parser")


class HtmlParser(Parser):
    format = SourceFormat.HTML

    def parse_metadata(self, source: str) -> DocumentMetadata:
        soup = _load(source)

        title_tag = soup.find("title")
        html_tag = soup.find("html")

        def meta_content(name: str) -> str | None:
            tag = soup.find("meta", attrs={"name": name})
            return attr_str(tag, "content") if isinstance(tag, Tag) else None

        author = meta_content("author")
        return DocumentMetadata(
            source_format=SourceFormat.HTML,
            title=title_tag.get_text(strip=True) if title_tag else None,
            creators=[author] if author else [],
            language=attr_str(html_tag, "lang") if isinstance(html_tag, Tag) else None,
            description=meta_content("description"),
        )

    def iter_units(self, source: str) -> Iterator[Unit]:
        soup = _load(source)
        body = soup.find("body") or soup
        yield from top_level_units(body)
