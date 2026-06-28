import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_TF_MARKER_FILES = {"otext.tf", "otype.tf"}


def _find_dataset_dirs(root: Path) -> list[Path]:
    """Return every directory under root that contains both otext.tf and otype.tf."""
    results = []
    for path in root.rglob("otext.tf"):
        candidate = path.parent
        if (candidate / "otype.tf").exists():
            results.append(candidate)
    return results


def fetch_datasets_from_git(git_url: str, temp_base: Path | None = None) -> list[Path]:
    """Clone a git repository and return paths of Text-Fabric dataset directories.

    A dataset directory is any folder that contains both otext.tf and otype.tf.
    The clone is placed under temp_base/.temp (defaults to cwd/.temp).

    Raises:
        subprocess.CalledProcessError: if git clone fails.
        FileNotFoundError: if git is not available on PATH.
    """
    if temp_base is None:
        temp_base = Path.cwd()

    temp_dir = temp_base / ".temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    clone_dir = Path(tempfile.mkdtemp(dir=temp_dir))
    try:
        logger.info("Cloning %s into %s", git_url, clone_dir)
        subprocess.run(
            ["git", "clone", "--depth=1", git_url, str(clone_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
        datasets = _find_dataset_dirs(clone_dir)
        logger.info("Found %d dataset(s) in %s", len(datasets), git_url)
        return datasets
    except Exception:
        shutil.rmtree(clone_dir, ignore_errors=True)
        raise
