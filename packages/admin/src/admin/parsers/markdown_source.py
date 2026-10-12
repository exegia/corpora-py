"""Markdown structure with a verbatim source stream, including syntax/spacing.

Block source slices own the tokens; semantic children retain decoded content in
attributes instead of repeating it in the stream. This makes offsets reproducible
without pretending rendered Markdown has the same characters as its source.
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path

from markdown_it import MarkdownIt

from .schema import DocumentMetadata, Parser, SourceFormat, Unit, read_source_bytes, tokenize


def markdown_units(text: str) -> list[Unit]:
    engine = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = engine.parse(text)
    lines = [line for line in re.findall(r".*?(?:\r\n|\r|\n|$)", text, re.DOTALL) if line]
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    root = Unit(type="markdown")
    stack = [root]
    headings: list[Unit] = []
    claimed = 0

    def inline(items):
        holder = Unit(type="inline")
        parents = [holder]
        for token in items or []:
            if token.nesting == -1:
                parents.pop()
                continue
            node = Unit(type=token.type.removesuffix("_open"), attrs=dict(token.attrs))
            if token.content:
                node.attrs["content"] = token.content
            if token.markup:
                node.attrs["markup"] = token.markup
            if token.children:
                node.children = inline(token.children)
            parents[-1].children.append(node)
            if token.nesting == 1:
                parents.append(node)
        return holder.children

    for token in tokens:
        if token.nesting == -1:
            stack.pop()
            continue
        if token.type == "inline":
            stack[-1].children.extend(inline(token.children))
            if stack[-1].type == "heading":
                stack[-1].label = token.content
                if headings:
                    headings[-1].label = token.content
            continue
        if token.type == "heading_open" and len(stack) == 1:
            level = int(token.tag[1:])
            while headings and int(headings[-1].attrs["level"]) >= level:
                headings.pop()
            section = Unit(type="section", attrs={"level": str(level)})
            (headings[-1].children if headings else root.children).append(section)
            headings.append(section)
        node = Unit(type=token.type.removesuffix("_open"), attrs=dict(token.attrs))
        if token.tag:
            node.attrs["tag"] = token.tag
        if token.markup:
            node.attrs["markup"] = token.markup
        if token.info:
            node.attrs["info"] = token.info
        if token.content:
            node.attrs["content"] = token.content
        if token.map:
            node.attrs["source_lines"] = json.dumps(token.map)
        if len(stack) == 1:
            if token.map:
                end = offsets[token.map[1]]
                node.tokens = tokenize(text[claimed:end])
                node.attrs["source_start"] = str(claimed)
                node.attrs["source_end"] = str(end)
                claimed = end
            (headings[-1].children if headings else root.children).append(node)
        else:
            stack[-1].children.append(node)
        if token.nesting == 1:
            stack.append(node)
    if claimed < len(text):
        (headings[-1].children if headings else root.children).append(
            Unit(type="source_trivia", tokens=tokenize(text[claimed:]))
        )
    return [root]


class MarkdownParser(Parser):
    format = SourceFormat.MARKDOWN

    def parse_metadata(self, source: str) -> DocumentMetadata:
        return DocumentMetadata(
            source_format=self.format,
            title=Path(source).stem,
            extra={
                "markdown:stream": "Verbatim UTF-8 source, including syntax and whitespace",
                "markdown:dialect": "CommonMark with tables; raw HTML retained as source text",
            },
        )

    def iter_units(self, source: str) -> Iterator[Unit]:
        yield from markdown_units(read_source_bytes(source).decode("utf-8"))
