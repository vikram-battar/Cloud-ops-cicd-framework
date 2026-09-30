"""Check and apply OS package updates.

Supports apt (Debian/Ubuntu) and yum/dnf (RHEL family) via a small
package-manager abstraction. Dry-run is the default: the tool only
reports what *would* change unless --apply is passed.

Usage:
    python3 -m ops.patching [--package-manager apt|yum] [--apply] [--json] [-v]
    # or, from the repo root:
    python3 ops/patching.py --json
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Optional, Sequence

log = logging.getLogger(__name__)


@dataclass
class PendingUpdate:
    package: str
    installed_version: str
    candidate_version: str


def detect_package_manager() -> Optional[str]:
    """Return 'apt' or 'yum' based on available binaries, else None."""
    if shutil.which("apt-get"):
        return "apt"
    if shutil.which("dnf") or shutil.which("yum"):
        return "yum"
    return None


def parse_apt_list_upgradable(text: str) -> list[PendingUpdate]:
    """Parse `apt list --upgradable` output into PendingUpdate records."""
    updates: list[PendingUpdate] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("Listing"):
            continue
        # e.g. "bash/jammy-updates 5.1-6ubuntu1.1 amd64 [upgradable from: 5.1-6ubuntu1]"
        try:
            name, rest = line.split("/", 1)
            candidate = rest.split()[1]
            installed = ""
            if "upgradable from:" in line:
                installed = line.split("upgradable from:")[1].rstrip("]").strip()
            updates.append(
                PendingUpdate(
                    package=name,
                    installed_version=installed,
                    candidate_version=candidate,
                )
            )
        except (IndexError, ValueError):
            log.debug("skipping unparsable apt line: %r", line)
    return updates


def parse_yum_check_update(text: str) -> list[PendingUpdate]:
    """Parse `yum/dnf check-update` output into PendingUpdate records."""
    updates: list[PendingUpdate] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("Loading", "Last metadata")):
            continue
        # body lines look like: "bash.x86_64    5.1.8-6.el9    baseos"
        parts = stripped.split()
        if len(parts) >= 2 and "." in parts[0]:
            package = parts[0].rsplit(".", 1)[0]
            updates.append(
                PendingUpdate(
                    package=package,
                    installed_version="",
                    candidate_version=parts[1],
                )
            )
    return updates


def get_pending_updates(package_manager: Optional[str] = None) -> list[PendingUpdate]:
    """Return the list of pending updates for the detected (or given) PM."""
    pm = package_manager or detect_package_manager()
    if pm is None:
        raise RuntimeError(
            "no supported package manager found (looked for apt-get, dnf, yum)"
        )
    if pm == "apt":
        proc = subprocess.run(
            ["apt", "list", "--upgradable"],
            capture_output=True,
            text=True,
            check=False,
        )
        return parse_apt_list_upgradable(proc.stdout)
    if pm == "yum":
        binary = "dnf" if shutil.which("dnf") else "yum"
        proc = subprocess.run(
            [binary, "check-update"],
            capture_output=True,
            text=True,
            check=False,
        )
        # dnf/yum check-update: 0 = no updates, 100 = updates available, 1 = error
        if proc.returncode == 1:
            raise RuntimeError(f"{binary} check-update failed: {proc.stderr.strip()}")
        return parse_yum_check_update(proc.stdout)
    raise ValueError(f"unsupported package manager: {pm}")


def apply_updates(
    updates: Sequence[PendingUpdate],
    package_manager: str,
    dry_run: bool = True,
) -> dict:
    """Apply updates. With dry_run=True only logs what would happen."""
    if dry_run:
        log.info(
            "dry-run: would upgrade %d package(s) via %s",
            len(updates),
            package_manager,
        )
        for update in updates:
            log.info(
                "dry-run: %s %s -> %s",
                update.package,
                update.installed_version or "?",
                update.candidate_version,
            )
        return {
            "applied": 0,
            "dry_run": True,
            "packages": [u.package for u in updates],
        }
    if package_manager == "apt":
        cmd = ["apt-get", "upgrade", "-y"]
    elif package_manager == "yum":
        binary = "dnf" if shutil.which("dnf") else "yum"
        cmd = [binary, "update", "-y"]
    else:
        raise ValueError(f"unsupported package manager: {package_manager}")
    log.info("applying %d update(s): %s", len(updates), " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"package upgrade failed: {proc.stderr.strip()[:500]}")
    return {
        "applied": len(updates),
        "dry_run": False,
        "packages": [u.package for u in updates],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check (and optionally apply) OS package updates. "
        "Dry-run by default."
    )
    parser.add_argument(
        "--package-manager",
        choices=["apt", "yum"],
        default=None,
        help="force a package manager instead of auto-detecting",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually apply updates (default is dry-run / report only)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON output")
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
    try:
        pm = args.package_manager or detect_package_manager()
        if pm is None:
            raise RuntimeError(
                "no supported package manager found (looked for apt-get, dnf, yum)"
            )
        updates = get_pending_updates(pm)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2

    if args.json:
        print(json.dumps([asdict(u) for u in updates], indent=2))
    else:
        for update in updates:
            print(
                f"{update.package}: {update.installed_version or '?'} "
                f"-> {update.candidate_version}"
            )
        print(f"{len(updates)} pending update(s) via {pm}")

    if args.apply:
        if not updates:
            print("nothing to apply")
            return 0
        result = apply_updates(updates, pm, dry_run=False)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"applied {result['applied']} update(s)")
    else:
        # dry-run pass: logs intent, changes nothing
        apply_updates(updates, pm, dry_run=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
