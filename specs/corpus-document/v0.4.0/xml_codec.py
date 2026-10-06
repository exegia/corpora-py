"""Reference typed XML representation; application adapters remain separate."""

import base64
import json
import math
import xml.etree.ElementTree as ET

NS = "urn:corpora:corpus-document:xml:0.4.0"
ET.register_namespace("", NS)


def encode(value):
    def element(tag):
        return ET.Element(f"{{{NS}}}{tag}")

    def visit(item):
        if isinstance(item, dict):
            node = element("object")
            for key, child in item.items():
                member = element("member")
                member.set("name", base64.b64encode(key.encode("utf-8")).decode("ascii"))
                member.append(visit(child))
                node.append(member)
        elif isinstance(item, list):
            node = element("array")
            node.extend(visit(child) for child in item)
        elif isinstance(item, str):
            node = element("string")
            node.text = base64.b64encode(item.encode("utf-8")).decode("ascii")
        elif item is None:
            node = element("null")
        elif isinstance(item, bool):
            node = element("boolean")
            node.text = "true" if item else "false"
        elif isinstance(item, (int, float)):
            node = element("number")
            node.text = json.dumps(item, allow_nan=False)
        else:
            raise ValueError("Not a JSON value")
        return node

    root = element("document")
    root.append(visit(value))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def decode(data):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("DTD and entity declarations forbidden")
    # UTF-8 wire encoding is mandatory, also prevents UTF-16 declaration bypass.
    root = ET.fromstring(data.decode("utf-8"))
    if root.tag != f"{{{NS}}}document" or len(root) != 1 or root.attrib:
        raise ValueError("Invalid document root")

    for element in root.iter():
        if element.tail and element.tail.strip():
            raise ValueError("Mixed content forbidden")
        if len(element) and element.text and element.text.strip():
            raise ValueError("Mixed content forbidden")

    def visit(node):
        if not node.tag.startswith(f"{{{NS}}}") or node.attrib:
            raise ValueError("Unknown value or attributes")
        tag = node.tag.split("}", 1)[1]
        if tag == "object":
            result = {}
            for member in node:
                if (
                    member.tag != f"{{{NS}}}member"
                    or set(member.attrib) != {"name"}
                    or len(member) != 1
                ):
                    raise ValueError("Invalid object member")
                key = base64.b64decode(member.attrib["name"], validate=True).decode("utf-8")
                if key in result:
                    raise ValueError("Duplicate member")
                result[key] = visit(member[0])
            return result
        if tag == "array":
            return [visit(child) for child in node]
        if len(node):
            raise ValueError("Scalar has children")
        content = node.text or ""
        if tag == "string":
            return base64.b64decode(content, validate=True).decode("utf-8")
        if tag == "null" and not content:
            return None
        if tag == "boolean" and content in ("true", "false"):
            return content == "true"
        if tag == "number":
            value = json.loads(
                content,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite number")),
            )
            if type(value) not in (int, float):
                raise ValueError("Invalid number")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Nonfinite number")
            return value
        raise ValueError("Invalid scalar")

    return visit(root[0])
