"""Export a standalone, independently testable source tree; never publish it."""

import argparse
import re
import shutil
from pathlib import Path

CORE_TESTS = ("test_detection.py", "test_resolution.py", "test_scholarly.py")
EXAMPLES = ("manual_link.py", "resolve_link.py", "scholarly_link.py")


def export(destination: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    source = root / "packages/linking"
    if destination.exists():
        raise ValueError("export destination must not exist")
    destination.mkdir(parents=True)
    for name in ("pyproject.toml", "LICENSE"):
        shutil.copy2(source / name, destination / name)
    shutil.copytree(
        source / "src", destination / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    (destination / "examples").mkdir()
    for name in EXAMPLES:
        shutil.copy2(source / "examples" / name, destination / "examples" / name)
    (destination / "tests/linking").mkdir(parents=True)
    for name in CORE_TESTS:
        text = (root / "tests/linking" / name).read_text()
        # Preserve the actual assertions; adjust only monorepo example paths.
        text = text.replace('"packages/linking/examples/', '"examples/')
        (destination / "tests/linking" / name).write_text(text)
    readme = (source / "README.md").read_text().split("## Corpora conversion integration")[0]
    readme = readme.replace(
        "uv build --package corpora-linking --wheel --out-dir dist/", "python -m build"
    )
    readme = readme.replace("uv run python packages/linking/examples/", "python examples/")
    readme = readme.replace("uv run pytest tests/linking", "python -m pytest tests")
    readme = readme.replace(
        "[implementation specification](../../specs/reference-linking/spec.md)",
        "[implementation specification](docs/spec.md)",
    )
    readme += "\n## Scholarly intake\n\nRun `python examples/scholarly_link.py`. Unknown works remain stable discovery records; catalog hypotheses never imply an exact passage.\n\n## Installation and release\n\nInstall with `pip install .`; development checks use `pip install pytest build`. Version 0.1.0 is provisional and unpublished. This export has no publication automation. Review naming, compatibility, release notes and registry availability before any separate authorized public release.\n\nFormat adapters, authentication, storage and C-USX belong to the [Corpora integration](https://github.com/exegia/corpora-py/tree/dev/specs/reference-linking). This package performs no I/O and depends only on Pydantic.\n"
    (destination / "README.md").write_text(readme)
    (destination / "docs").mkdir()
    for name in ("spec.md", "locators.md", "scholarly.md"):
        path = root / "specs/reference-linking" / name
        if path.exists():
            text = path.read_text()

            def external_link(match, document_path=path):
                target = match.group(1)
                if ":" in target or target.startswith("#"):
                    return match.group(0)
                relative = (document_path.parent / target).resolve().relative_to(root)
                return "](https://github.com/exegia/corpora-py/blob/dev/" + str(relative) + ")"

            text = re.sub(r"\]\(([^)]+)\)", external_link, text)
            (destination / "docs" / name).write_text(text)
    instructions = """# Agent instructions

Keep the core independent of storage, UI, XML and heavyweight parsers.
Read README.md and docs/spec.md. Preserve opaque IDs and exact revisions.
Never guess ambiguous works, relocate stale selections or use vectors as exact
retrieval authority. Validate wire inputs and retain unresolved evidence.
Run python -m pytest tests, python -m build, and install the actual wheel in a
fresh environment away from this tree. No publish/deploy without authorization.
"""
    (destination / "AGENTS.md").write_text(instructions)
    (destination / "CLAUDE.md").write_text("Read and follow AGENTS.md.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    export(parser.parse_args().destination.resolve())
