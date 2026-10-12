"""Publish verified sidecars, using a companion release when the source is immutable."""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

PLATFORMS = {"macos-arm64", "macos-x64", "windows-x64"}
CHECKS = {
    "extracted runtime",
    "API health",
    "SQLite",
    "XML",
    "CTEI conversion",
    "TEI schema hashes",
}


def api(path: str, *, optional: bool = False):
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if optional and result.returncode and "HTTP 404" in result.stderr:
        return None
    result.check_returncode()
    return json.loads(result.stdout)


def verified_files(root: Path, tag: str, source_sha: str, run_id: str, repo: str):
    expected = {
        f"corpora-py-{platform}.{suffix}" for platform in PLATFORMS for suffix in ("zip", "json")
    }
    actual = {path.name for suffix in ("*.zip", "*.json") for path in root.glob(suffix)}
    if actual != expected:
        raise ValueError("Expected exactly three platform ZIPs and three provenance records")
    receipts = {}
    for platform in PLATFORMS:
        receipt = json.loads((root / f"corpora-py-{platform}.json").read_text(encoding="utf-8"))
        if (
            receipt["platform"] != platform
            or receipt["version"] != tag.removeprefix("v")
            or receipt["source_commit"] != source_sha
            or receipt["workflow_run"] != f"https://github.com/{repo}/actions/runs/{run_id}"
            or not CHECKS.issubset(receipt["verification"])
            or type(receipt["signed"]) is not bool
        ):
            raise ValueError(f"Unverified provenance for {platform}")
        archive = root / f"corpora-py-{platform}.zip"
        if hashlib.sha256(archive.read_bytes()).hexdigest() != receipt["archive_sha256"]:
            raise ValueError(f"Archive checksum mismatch for {platform}")
        receipts[platform] = receipt
    if len({receipt["wheel_sha256"] for receipt in receipts.values()}) != 1:
        raise ValueError("Platforms must bundle the same source wheel")
    return receipts


def publish(tag: str, root: Path) -> None:
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", tag):
        raise ValueError("An existing release version tag is required")
    repo = os.environ["GH_REPO"]
    run_id = os.environ["ARTIFACT_RUN_ID"]
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise ValueError("A numeric sidecar workflow run ID is required")
    source = api(f"repos/{repo}/releases/tags/{tag}")
    if source["draft"]:
        raise ValueError("Source release must already be published")
    ref = api(f"repos/{repo}/git/ref/tags/{tag}")["object"]
    while ref["type"] == "tag":
        ref = api(f"repos/{repo}/git/tags/{ref['sha']}")["object"]
    source_sha = ref["sha"]
    receipts = verified_files(root, tag, source_sha, run_id, repo)
    run = api(f"repos/{repo}/actions/runs/{run_id}")
    if run["path"] != ".github/workflows/build-sidecar.yml":
        raise ValueError("Artifacts must come from the sidecar workflow")
    if any(receipt["workflow_commit"] != run["head_sha"] for receipt in receipts.values()):
        raise ValueError("Build commit does not match the artifact workflow run")
    jobs = api(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100")["jobs"]
    for platform in PLATFORMS:
        if not any(
            job["name"] == f"Bundle ({platform})" and job["conclusion"] == "success" for job in jobs
        ):
            raise ValueError(f"Native {platform} verification must succeed before publishing")

    files = sorted(root.glob("corpora-py-*.zip")) + sorted(root.glob("corpora-py-*.json"))
    checksums = root / "corpora-py-sidecars-SHA256SUMS.txt"
    checksums.write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in files
        ),
        encoding="utf-8",
    )
    files.append(checksums)
    target_tag = f"sidecars/{tag}" if source.get("immutable") else tag
    target_path = f"repos/{repo}/releases/tags/{quote(target_tag, safe='')}"
    target = api(target_path, optional=True)
    unsigned = any(not receipt["signed"] for receipt in receipts.values())
    if target is None:
        notes = (
            f"Desktop Python runtime bundles for **Corpora API {tag}**.\n\n"
            f"Source: [{tag}]({source['html_url']}), commit `{source_sha}`.\n\n"
            f"{'These bundles are unsigned.' if unsigned else 'These bundles are signed.'} "
            "Each ZIP passed verification on its native platform: extracted runtime, API health, "
            "SQLite, XML, TEI schema hashes and `.ctei` conversion. "
            "Provenance JSON and SHA256 checksums accompany all three platforms.\n\n"
            "This companion release supplies the missing desktop assets for the immutable source release.\n"
        )
        subprocess.run(
            [
                "gh",
                "release",
                "create",
                target_tag,
                "--draft",
                "--target",
                source_sha,
                "--title",
                f"{tag} desktop bundles" + (" (unsigned)" if unsigned else ""),
                "--notes",
                notes,
            ],
            check=True,
        )
        target = api(target_path)
    existing = {asset["name"]: asset for asset in target["assets"]}
    uploads = []
    for path in files:
        if path.name in existing:
            digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
            if existing[path.name].get("digest") != digest:
                raise ValueError(f"Existing asset differs: {path.name}; refusing overwrite")
            continue
        if target.get("immutable"):
            raise ValueError("Published companion release is immutable and missing assets")
        label = ("Unsigned sidecar bundle: " if unsigned else "Sidecar bundle: ") + path.name
        uploads.append(str(path) + (f"#{label}" if path.suffix == ".zip" else ""))
    if uploads:
        subprocess.run(["gh", "release", "upload", target_tag, *uploads], check=True)
    if target["draft"]:
        subprocess.run(
            ["gh", "release", "edit", target_tag, "--draft=false", "--latest=false"], check=True
        )
    published = api(target_path)
    if target_tag != tag and published["html_url"] not in (source["body"] or ""):
        notes = (
            (source["body"] or "")
            + f"\n\nDesktop bundles: [{tag} desktop bundles]({published['html_url']})"
            + (" (unsigned).\n" if unsigned else ".\n")
        )
        with tempfile.TemporaryDirectory() as temporary:
            notes_file = Path(temporary) / "release-notes.md"
            notes_file.write_text(notes, encoding="utf-8")
            subprocess.run(
                ["gh", "release", "edit", tag, "--notes-file", str(notes_file)], check=True
            )
    print(f"Published verified desktop bundles: {published['html_url']}")


if __name__ == "__main__":
    publish(sys.argv[1], Path(sys.argv[2]))
