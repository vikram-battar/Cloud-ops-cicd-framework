"""Collect local instance metadata and emit it as JSON.

Local-only: reads /proc, /etc/os-release and DMI data. Makes no network
calls, so it is safe to run anywhere (CI, containers, laptops).

Usage:
    python3 ops/inventory.py [--pretty] [--output inventory.json]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import shutil
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

log = logging.getLogger(__name__)


def get_hostname() -> str:
    return socket.gethostname()


def parse_os_release(path: str = "/etc/os-release") -> dict:
    """Parse /etc/os-release into a dict; empty dict if unreadable."""
    info: dict = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                info[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        log.debug("cannot read %s", path)
    return info


def get_os_info() -> dict:
    os_release = parse_os_release()
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "distro_name": os_release.get("NAME", ""),
        "distro_version": os_release.get("VERSION_ID", ""),
        "distro_id": os_release.get("ID", ""),
    }


def get_memory_mb() -> dict:
    """Return total/available memory in MiB from /proc/meminfo (Linux)."""
    meminfo = Path("/proc/meminfo")
    total = available = None
    try:
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                total = int(line.split()[1]) // 1024
            elif line.startswith("MemAvailable:"):
                available = int(line.split()[1]) // 1024
    except OSError:
        log.debug("cannot read /proc/meminfo")
    return {"total_mb": total, "available_mb": available}


def get_disk_usage(path: str = "/") -> dict:
    usage = shutil.disk_usage(path)
    return {
        "path": path,
        "total_gb": round(usage.total / (1024**3), 2),
        "used_gb": round(usage.used / (1024**3), 2),
        "free_gb": round(usage.free / (1024**3), 2),
    }


def get_uptime_seconds() -> Optional[float]:
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as handle:
            return float(handle.read().split()[0])
    except OSError:
        return None


def _read_dmi_file(name: str) -> str:
    try:
        return (Path("/sys/class/dmi/id") / name).read_text(
            encoding="utf-8"
        ).strip().lower()
    except OSError:
        return ""


def detect_cloud_vendor() -> str:
    """Best-effort cloud detection from DMI data and env vars (no network)."""
    blob = f"{_read_dmi_file('sys_vendor')} {_read_dmi_file('product_name')}"
    if "amazon" in blob:
        return "aws"
    if "google" in blob:
        return "gcp"
    if "microsoft" in blob:
        return "azure"
    if os.environ.get("AWS_EXECUTION_ENV"):
        return "aws"
    if os.environ.get("GCE_METADATA_HOST"):
        return "gcp"
    return "unknown"


def collect_inventory() -> dict:
    """Gather all inventory facts into one JSON-serialisable dict."""
    return {
        "hostname": get_hostname(),
        "os": get_os_info(),
        "cpu_count": os.cpu_count(),
        "memory_mb": get_memory_mb(),
        "disk": get_disk_usage("/"),
        "uptime_seconds": get_uptime_seconds(),
        "cloud_vendor": detect_cloud_vendor(),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "tool_version": "0.1.0",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect local instance metadata as JSON (no network calls)."
    )
    parser.add_argument(
        "--output",
        default=None,
        help="write JSON to this file instead of stdout",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="pretty-print JSON with indentation",
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
    payload = json.dumps(collect_inventory(), indent=2 if args.pretty else None)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
        print(f"wrote inventory to {args.output}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
