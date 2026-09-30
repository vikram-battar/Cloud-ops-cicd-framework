"""Unit tests for the ops package. No network, no root, no real package installs."""

import gzip
import os
import time
from pathlib import Path

from ops import inventory, log_rotation, patching


# ---------------------------------------------------------------- patching

SAMPLE_APT = """Listing... Done
bash/jammy-updates 5.1-6ubuntu1.1 amd64 [upgradable from: 5.1-6ubuntu1]
curl/jammy-updates 7.81.0-1ubuntu1.15 amd64 [upgradable from: 7.81.0-1ubuntu1.10]
"""

SAMPLE_YUM = """Loading mirror speeds from cached hostfile
Last metadata expiration check: 0:12:33 ago on Mon 01 Jan 2024.
bash.x86_64    5.1.8-6.el9     baseos
curl.x86_64    7.76.1-26.el9   appstream
"""


def test_parse_apt_list_upgradable():
    updates = patching.parse_apt_list_upgradable(SAMPLE_APT)
    assert len(updates) == 2
    assert updates[0].package == "bash"
    assert updates[0].installed_version == "5.1-6ubuntu1"
    assert updates[0].candidate_version == "5.1-6ubuntu1.1"
    assert updates[1].package == "curl"


def test_parse_apt_skips_header_and_blank_lines():
    assert patching.parse_apt_list_upgradable("Listing... Done\n\n") == []
    # garbage lines are skipped, not fatal
    assert patching.parse_apt_list_upgradable("not a real line\n") == []


def test_parse_yum_check_update():
    updates = patching.parse_yum_check_update(SAMPLE_YUM)
    assert [u.package for u in updates] == ["bash", "curl"]
    assert updates[0].candidate_version == "5.1.8-6.el9"


def test_detect_package_manager_prefers_apt(monkeypatch):
    monkeypatch.setattr(
        patching.shutil, "which", lambda name: "/usr/bin/apt-get" if name == "apt-get" else None
    )
    assert patching.detect_package_manager() == "apt"


def test_detect_package_manager_falls_back_to_yum(monkeypatch):
    def fake_which(name):
        return "/usr/bin/yum" if name == "yum" else None

    monkeypatch.setattr(patching.shutil, "which", fake_which)
    assert patching.detect_package_manager() == "yum"


def test_detect_package_manager_none_found(monkeypatch):
    monkeypatch.setattr(patching.shutil, "which", lambda name: None)
    assert patching.detect_package_manager() is None


class _Completed:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_get_pending_updates_apt_uses_parser(monkeypatch):
    monkeypatch.setattr(
        patching.subprocess, "run", lambda *a, **k: _Completed(stdout=SAMPLE_APT)
    )
    updates = patching.get_pending_updates("apt")
    assert len(updates) == 2
    assert updates[0].package == "bash"


def test_get_pending_updates_yum_ignores_exit_100(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return _Completed(stdout=SAMPLE_YUM, returncode=100)

    monkeypatch.setattr(patching.subprocess, "run", fake_run)
    monkeypatch.setattr(patching.shutil, "which", lambda name: None)
    updates = patching.get_pending_updates("yum")
    assert seen["cmd"][0] == "yum"  # dnf not present -> yum
    assert len(updates) == 2


def test_apply_updates_dry_run_never_shells_out(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("subprocess must not run in dry-run mode")

    monkeypatch.setattr(patching.subprocess, "run", _boom)
    result = patching.apply_updates(
        [patching.PendingUpdate("bash", "1", "2")], "apt", dry_run=True
    )
    assert result["dry_run"] is True
    assert result["applied"] == 0
    assert result["packages"] == ["bash"]


def test_apply_updates_real_mode_runs_upgrade_command(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Completed()

    monkeypatch.setattr(patching.subprocess, "run", fake_run)
    result = patching.apply_updates(
        [patching.PendingUpdate("bash", "1", "2")], "apt", dry_run=False
    )
    assert result["applied"] == 1
    assert calls[0][:2] == ["apt-get", "upgrade"]


def test_main_returns_error_when_no_package_manager(monkeypatch, capsys):
    monkeypatch.setattr(patching, "detect_package_manager", lambda: None)
    assert patching.main([]) == 2


# ------------------------------------------------------------ log rotation


def _make_old_log(path: Path, days_old: int = 10, content: str = "line1\nline2\n"):
    path.write_text(content)
    old = time.time() - days_old * 86400
    os.utime(path, (old, old))


def test_rotate_directory_compresses_old_logs(tmp_path):
    old_log = tmp_path / "app.log"
    _make_old_log(old_log, days_old=10)
    fresh_log = tmp_path / "fresh.log"
    fresh_log.write_text("new\n")

    result = log_rotation.rotate_directory(tmp_path, days=7)

    assert len(result.rotated) == 1
    assert result.dry_run is False
    archive = tmp_path / "app.log.gz"
    assert archive.exists()
    assert not old_log.exists()  # original removed
    assert fresh_log.exists()  # too new, untouched
    with gzip.open(archive, "rt") as handle:
        assert handle.read() == "line1\nline2\n"


def test_rotate_directory_dry_run_changes_nothing(tmp_path):
    old_log = tmp_path / "app.log"
    _make_old_log(old_log, days_old=10)

    result = log_rotation.rotate_directory(tmp_path, days=7, dry_run=True)

    assert result.dry_run is True
    assert len(result.rotated) == 1  # would-have-rotated
    assert old_log.exists()
    assert not (tmp_path / "app.log.gz").exists()


def test_rotate_directory_rejects_missing_dir(tmp_path):
    try:
        log_rotation.rotate_directory(tmp_path / "nope", days=7)
    except ValueError as exc:
        assert "not a directory" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_delete_old_archives(tmp_path):
    archive = tmp_path / "old.log.gz"
    with gzip.open(archive, "wt") as handle:
        handle.write("x\n")
    old = time.time() - 40 * 86400
    os.utime(archive, (old, old))

    result = log_rotation.rotate_directory(
        tmp_path, days=7, delete_archives_older_than=30
    )
    assert len(result.deleted) == 1
    assert not archive.exists()


def test_archives_newer_than_threshold_are_kept(tmp_path):
    archive = tmp_path / "recent.log.gz"
    with gzip.open(archive, "wt") as handle:
        handle.write("x\n")

    result = log_rotation.rotate_directory(
        tmp_path, days=7, delete_archives_older_than=30
    )
    assert result.deleted == []
    assert archive.exists()


# --------------------------------------------------------------- inventory


def test_collect_inventory_shape(monkeypatch):
    monkeypatch.setattr(inventory.socket, "gethostname", lambda: "testhost")
    inv = inventory.collect_inventory()
    for key in (
        "hostname",
        "os",
        "cpu_count",
        "memory_mb",
        "disk",
        "uptime_seconds",
        "cloud_vendor",
        "collected_at",
    ):
        assert key in inv, f"missing key: {key}"
    assert inv["hostname"] == "testhost"
    assert inv["os"]["system"]  # non-empty on any platform


def test_parse_os_release(tmp_path):
    fake = tmp_path / "os-release"
    fake.write_text('NAME="Ubuntu"\nVERSION_ID="22.04"\nID=ubuntu\n')
    info = inventory.parse_os_release(str(fake))
    assert info["ID"] == "ubuntu"
    assert info["VERSION_ID"] == "22.04"


def test_parse_os_release_missing_file_returns_empty(tmp_path):
    assert inventory.parse_os_release(str(tmp_path / "missing")) == {}


def test_detect_cloud_vendor_unknown_when_no_hints(monkeypatch):
    monkeypatch.setattr(inventory, "_read_dmi_file", lambda name: "")
    monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)
    monkeypatch.delenv("GCE_METADATA_HOST", raising=False)
    assert inventory.detect_cloud_vendor() == "unknown"


def test_detect_cloud_vendor_from_dmi(monkeypatch):
    monkeypatch.setattr(
        inventory, "_read_dmi_file", lambda name: "amazon ec2" if name == "sys_vendor" else ""
    )
    assert inventory.detect_cloud_vendor() == "aws"


def test_main_writes_output_file(tmp_path, monkeypatch):
    monkeypatch.setattr(inventory.socket, "gethostname", lambda: "testhost")
    out = tmp_path / "inv.json"
    assert inventory.main(["--output", str(out)]) == 0
    assert '"hostname": "testhost"' in out.read_text()
