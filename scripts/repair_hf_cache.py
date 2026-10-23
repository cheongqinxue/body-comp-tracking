"""Repair broken Hugging Face cache symlinks on NTFS/exFAT drives."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

DEFAULT_MODEL_CACHE = (
    Path(os.environ.get("HF_HUB_CACHE", Path.home() / ".cache" / "huggingface" / "hub"))
    / "models--numind--NuExtract3-W8A8"
)


def _extract_blob_name(path: Path) -> str | None:
    """Return the blob filename referenced by a broken cache symlink file.

    Args:
        path: Snapshot file that may contain symlink metadata instead of content.

    Returns:
        Blob filename under ``blobs/``, or ``None`` when not a repairable link.
    """
    raw = path.read_bytes()
    if b"blobs/" not in raw and not raw.startswith(b"IntxLNK"):
        return None

    for encoding in ("utf-16-le", "utf-8"):
        text = raw.decode(encoding, errors="ignore")
        match = re.search(r"blobs[/\\]([0-9a-f]+)", text)
        if match:
            return match.group(1)
    return None


def _is_valid_snapshot_file(path: Path) -> bool:
    """Return whether a snapshot file already contains usable content.

    Args:
        path: Candidate snapshot file.

    Returns:
        True when the file can be read normally.
    """
    if not path.is_file() or path.stat().st_size == 0:
        return False

    if _extract_blob_name(path) is not None:
        return False

    try:
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
        elif path.suffix == ".jinja":
            text = path.read_text(encoding="utf-8")
            if "{%" not in text and "{{" not in text:
                return False
        else:
            with path.open("rb") as handle:
                handle.read(64)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False

    return True


def _needs_repair(path: Path) -> bool:
    """Return whether a snapshot file should be replaced from its blob copy.

    Args:
        path: Candidate snapshot file.

    Returns:
        True when the file appears to be a broken symlink stub.
    """
    blob_name = _extract_blob_name(path)
    if blob_name is None:
        return False

    if path.suffix in {".json", ".jinja"}:
        return not _is_valid_snapshot_file(path)

    # Weight files should be much larger than Windows symlink stubs on NTFS.
    return path.stat().st_size < 4096


def repair_model_cache(model_cache_dir: Path) -> int:
    """Replace broken snapshot symlinks with copied blob contents.

    Args:
        model_cache_dir: Hugging Face model cache directory, e.g.
            ``.../hub/models--numind--NuExtract3-W8A8``.

    Returns:
        Number of snapshot files repaired.
    """
    snapshots_dir = model_cache_dir / "snapshots"
    blobs_dir = model_cache_dir / "blobs"
    if not snapshots_dir.is_dir() or not blobs_dir.is_dir():
        raise FileNotFoundError(f"Cache layout not found under {model_cache_dir}")

    repaired = 0
    for snapshot_dir in snapshots_dir.iterdir():
        if not snapshot_dir.is_dir():
            continue

        for snapshot_file in snapshot_dir.iterdir():
            if not snapshot_file.is_file() or not _needs_repair(snapshot_file):
                continue

            blob_name = _extract_blob_name(snapshot_file)
            if blob_name is None:
                continue

            blob_path = blobs_dir / blob_name
            if not blob_path.is_file():
                continue

            snapshot_file.unlink()
            shutil.copy2(blob_path, snapshot_file)
            repaired += 1
            print(f"Repaired {snapshot_file.name} from blobs/{blob_name}")

    return repaired


def main() -> None:
    """Repair the configured NuExtract cache from the command line."""
    model_cache_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MODEL_CACHE
    repaired = repair_model_cache(model_cache_dir)
    print(f"Repaired {repaired} file(s) in {model_cache_dir}")


if __name__ == "__main__":
    main()
