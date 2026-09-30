"""Rotate and compress log files older than N days.

Finds files matching a pattern (default ``*.log``) under a directory whose
mtime is older than ``--days``, gzip-compresses them to ``<name>.log.gz``
and removes the original. Optionally deletes compressed archives older
than a second threshold. Dry-run mode changes nothing.

Usage:
    python3 ops/log_rotation.py /var/log/app --days 7 --dry-run
    python3 ops/log_rotation.py /var/log/app --days 7 --delete-archives-older-than 30
"""
from __future__ import annotations

import argparse
import gzip
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

log = logging.getLogger(__name__)


@dataclass
class RotationResult:
    rotated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    dry_run: bool = False


def find_candidate_logs(
    directory: Path, days: int, pattern: str = "*.log"
) -> list[Path]:
    """Return files matching *pattern* in *directory* older than *days*.

    Non-recursive by design: point it at the log directory itself.
    """
    cutoff = time.time() - days * 86400
    candidates = []
    for path in sorted(directory.glob(pattern)):
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                candidates.append(path)
        except OSError as exc:
            log.warning("cannot stat %s: %s", path, exc)
    return candidates


def rotate_log(path: Path) -> str:
    """Gzip *path* to ``path.gz`` and remove the original. Returns archive path."""
    target = path.with_name(path.name + ".gz")
    with path.open("rb") as src, gzip.open(target, "wb") as dst:
        shutil.copyfileobj(src, dst)
    path.unlink()
    return str(target)


def delete_old_archives(directory: Path, older_than_days: int) -> list[str]:
    """Delete ``*.log.gz`` archives older than *older_than_days*."""
    cutoff = time.time() - older_than_days * 86400
    deleted = []
    for archive in sorted(directory.glob("*.log.gz")):
        try:
            if archive.is_file() and archive.stat().st_mtime < cutoff:
                archive.unlink()
                deleted.append(str(archive))
        except OSError as exc:
            log.warning("cannot delete %s: %s", archive, exc)
    return deleted


def rotate_directory(
    directory: Path,
    days: int,
    pattern: str = "*.log",
    dry_run: bool = False,
    delete_archives_older_than: Optional[int] = None,
) -> RotationResult:
    """Rotate old logs in *directory*; return a summary of what happened."""
    result = RotationResult(dry_run=dry_run)
    if not directory.is_dir():
        raise ValueError(f"not a directory: {directory}")

    for candidate in find_candidate_logs(directory, days, pattern):
        if dry_run:
            log.info("dry-run: would rotate %s", candidate)
            result.rotated.append(str(candidate))
            continue
        try:
            archive = rotate_log(candidate)
            log.info("rotated %s -> %s", candidate, archive)
            result.rotated.append(archive)
        except OSError as exc:
            log.error("failed to rotate %s: %s", candidate, exc)
            result.skipped.append(str(candidate))

    if delete_archives_older_than is not None:
        if dry_run:
            cutoff = time.time() - delete_archives_older_than * 86400
            for archive in sorted(directory.glob("*.log.gz")):
                try:
                    if archive.stat().st_mtime < cutoff:
                        log.info("dry-run: would delete archive %s", archive)
                        result.deleted.append(str(archive))
                except OSError:
                    continue
        else:
            for archive in delete_old_archives(directory, delete_archives_older_than):
                log.info("deleted old archive %s", archive)
                result.deleted.append(archive)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compress log files older than N days (gzip) and "
        "optionally prune old archives."
    )
    parser.add_argument("directory", help="log directory to process")
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="rotate files older than this many days (default: 7)",
    )
    parser.add_argument(
        "--pattern",
        default="*.log",
        help="filename glob to match (default: *.log)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would happen without changing anything",
    )
    parser.add_argument(
        "--delete-archives-older-than",
        type=int,
        default=None,
        metavar="DAYS",
        help="also delete *.log.gz archives older than DAYS",
    )
    parser.add_argument(
        "-v", "--verbose", action="count", default=0, help="increase log verbosity"
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.days < 0:
        log.error("--days must be >= 0")
        return 2
    try:
        result = rotate_directory(
            Path(args.directory),
            days=args.days,
            pattern=args.pattern,
            dry_run=args.dry_run,
            delete_archives_older_than=args.delete_archives_older_than,
        )
    except ValueError as exc:
        log.error("%s", exc)
        return 2
    print(
        f"rotated={len(result.rotated)} "
        f"deleted={len(result.deleted)} "
        f"skipped={len(result.skipped)} "
        f"dry_run={result.dry_run}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
