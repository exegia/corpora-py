"""Read EPUB publication evidence without extracting untrusted ZIP paths."""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

from lxml import etree as etree

from ..parsers.schema import Document, DocumentMetadata, SourceFormat, Token, Unit


def local_path(base: str, href: str) -> str:
    parts = urlsplit(href)
    if parts.scheme or parts.netloc or parts.query:
        raise ValueError("External or queried publication resources are unsupported")
    path = posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(parts.path)))
    if path.startswith(("/", "../")) or path in {"..", "."} or "\\" in path:
        raise ValueError("Publication resource escapes the archive")
    return path


def xml(data: bytes):
    # XHTML doctypes are common in EPUB 2; entities/network access remain disabled.
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    root = etree.fromstring(data, parser)
    if any(isinstance(e, etree._Entity) for e in root.iter()):
        raise ValueError("Unresolved XHTML entities cannot be converted faithfully")
    return root


def tokens(value: str) -> list[Token]:
    matches = list(re.finditer(r"\S+", value))
    leading = value[: matches[0].start()] if matches else value
    result = [Token(text="", after=leading)] if leading else []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        result.append(Token(text=match.group(), after=value[match.end() : end]))
    return result


def build_unit(element, path: str) -> Unit:
    attrs = {etree.QName(k).localname: v for k, v in element.attrib.items()}
    attrs["source_path"] = path
    children = []

    def add_text(value):
        if value:
            children.append(
                Unit(
                    type="text",
                    attrs={"source_path": f"{path}/{len(children)}"},
                    tokens=tokens(value),
                )
            )

    add_text(element.text)
    for child in element:
        if isinstance(child.tag, str):
            tag = etree.QName(child).localname
            if tag in {"script", "style", "noscript"}:
                raise ValueError(f"Embedded {tag} content requires a supported adapter")
            if tag in {"math", "audio", "video", "iframe", "object", "form"}:
                raise ValueError(f"Unsupported EPUB content element: {tag}")
            children.append(build_unit(child, f"{path}/{len(children)}"))
        add_text(child.tail)
    return Unit(type=etree.QName(element).localname, attrs=attrs, children=children)


@dataclass
class Publication:
    document: Document
    metadata: dict[str, list[str]]
    texts: list[str]
    stylesheets: dict[str, str]
    section_css: dict[str, list[str]]
    labels: dict[str, str]
    navigation: list[tuple[str, str, int]]
    assets: list[tuple[str, str, bytes, bool]]
    warnings: list[str] = field(default_factory=list)


def read_publication(source: Path) -> Publication:
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        if len(infos) > 10000 or sum(i.file_size for i in infos) > 512 * 1024 * 1024:
            raise ValueError("EPUB exceeds the 10,000 resources / 512 MiB expanded limit")
        if len({i.filename for i in infos}) != len(infos):
            raise ValueError("Duplicate archive resource paths")
        if "META-INF/encryption.xml" in archive.namelist():
            raise ValueError("Encrypted or obfuscated EPUB resources are unsupported")
        container = xml(archive.read("META-INF/container.xml"))
        opf_path = local_path(
            "", container.xpath('//*[local-name()="rootfile"]')[0].get("full-path")
        )
        opf = xml(archive.read(opf_path))
        metadata: dict[str, list[str]] = {}
        for e in opf.xpath('//*[local-name()="metadata"]/*'):
            if etree.QName(e).namespace == "http://purl.org/dc/elements/1.1/":
                metadata.setdefault(etree.QName(e).localname, []).append("".join(e.itertext()))
        manifest = {}
        stylesheets, assets, labels, navigation = {}, [], {}, []
        cover_ids = set(opf.xpath('//*[local-name()="meta"][@name="cover"]/@content'))
        for item in opf.xpath('//*[local-name()="manifest"]/*'):
            path = local_path(opf_path, item.get("href", ""))
            key = item.get("id")
            if key in manifest:
                raise ValueError("Duplicate manifest identity")
            manifest[key] = (path, item.get("media-type", ""))
            media = item.get("media-type", "")
            data = archive.read(path)
            if media == "text/css":
                stylesheets[path] = data.decode("utf-8-sig")
            elif media.startswith(("image/", "audio/", "video/", "font/")) or media in {
                "application/vnd.ms-opentype",
                "application/font-woff",
                "application/x-font-ttf",
            }:
                assets.append(
                    (
                        path,
                        media,
                        data,
                        key in cover_ids
                        or "cover-image" in item.get("properties", "").split()
                        or key == "cover-image",
                    )
                )
            if media == "application/x-dtbncx+xml":
                nav = xml(data)
                for point in nav.xpath('//*[local-name()="navPoint"]'):
                    href = point.xpath('./*[local-name()="content"]/@src')[0]
                    label = "".join(
                        point.xpath('./*[local-name()="navLabel"]/*[local-name()="text"]')[
                            0
                        ].itertext()
                    ).strip()
                    target = local_path(path, href)
                    labels.setdefault(target, label)
                    depth = len(point.xpath('ancestor::*[local-name()="navPoint"]'))
                    navigation.append((target, label, depth))
            elif "nav" in item.get("properties", "").split():
                nav = xml(data)
                for a in nav.xpath('//*[local-name()="nav"]//*[local-name()="a"][@href]'):
                    target = local_path(path, a.get("href"))
                    label = "".join(a.itertext()).strip()
                    labels.setdefault(target, label)
                    navigation.append(
                        (target, label, len(a.xpath('ancestor::*[local-name()="ol"]')) - 1)
                    )
        units, texts, section_css = [], [], {}
        seen = set()
        for position, ref in enumerate(opf.xpath('//*[local-name()="spine"]/*')):
            if ref.get("idref") not in manifest:
                raise ValueError("Spine selects a missing manifest identity")
            path, media = manifest[ref.get("idref")]
            if path in seen or media not in {"application/xhtml+xml", "text/html"}:
                raise ValueError("Repeated or non-XHTML spine content is unsupported")
            seen.add(path)
            tree = xml(archive.read(path))
            bodies = tree.xpath('//*[local-name()="body"]')
            if len(bodies) != 1:
                raise ValueError("Spine content must have one body")
            # Text is never stripped or normalized across inline element boundaries.
            body = bodies[0]
            texts.append("".join(body.itertext()))
            unit = build_unit(body, str(position))
            unit.type, unit.id, unit.label = "chapter", ref.get("idref"), labels.get(path, "")
            unit.attrs["name"] = path
            units.append(unit)
            section_css[path] = [
                local_path(path, link.get("href"))
                for link in tree.xpath('//*[local-name()="link"][@href]')
                if "stylesheet" in link.get("rel", "").split()
            ]
            for number, style in enumerate(
                tree.xpath('//*[local-name()="head"]/*[local-name()="style"]')
            ):
                key = f"{path}#style-{number}"
                stylesheets[key] = "".join(style.itertext())
                section_css[path].append(key)
            for key in section_css[path]:
                if key not in stylesheets:
                    raise ValueError("Missing linked stylesheet")
        if not units:
            raise ValueError("EPUB has no readable spine content")
        md = DocumentMetadata(
            source_format=SourceFormat.EPUB,
            title=(metadata.get("title") or [None])[0],
            creators=metadata.get("creator", []),
            language=(metadata.get("language") or [None])[0],
            publisher=(metadata.get("publisher") or [None])[0],
            date=(metadata.get("date") or [None])[0],
            description=(metadata.get("description") or [None])[0],
            identifier=(metadata.get("identifier") or [None])[0],
            rights=(metadata.get("rights") or [None])[0],
            subjects=metadata.get("subject", []),
        )
        return Publication(
            Document(metadata=md, units=units),
            metadata,
            texts,
            stylesheets,
            section_css,
            labels,
            navigation,
            assets,
        )
