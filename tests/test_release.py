import subprocess
from pathlib import Path

import pytest
import tomlkit

from scripts import release


def test_atomic_write_text(tmp_path: Path) -> None:
    target = tmp_path / "test.txt"
    release.atomic_write_text(target, "hello world")
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "hello world"


def test_compute_bumped_version() -> None:
    assert release.compute_bumped_version("1.2.3", "major") == "2.0.0"
    assert release.compute_bumped_version("1.2.3", "minor") == "1.3.0"
    assert release.compute_bumped_version("1.2.3", "patch") == "1.2.4"
    assert release.compute_bumped_version("1.2.3-alpha.1", "minor") == "1.3.0"

    with pytest.raises(ValueError, match="not valid SemVer"):
        release.compute_bumped_version("invalid", "patch")

    with pytest.raises(ValueError, match="Invalid version part"):
        release.compute_bumped_version("1.0.0", "unknown")


@pytest.fixture
def mock_release_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Sets up a temporary working directory with pyproject.toml."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo-pkg"\nversion = "1.0.0"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    return pyproject


def test_main_missing_tool(mock_release_env: Path, mocker, capsys) -> None:
    mocker.patch("shutil.which", return_value=None)
    with pytest.raises(SystemExit) as exc:
        release.main(["minor"])
    assert exc.value.code == 1
    assert "Required tool 'git' not found" in capsys.readouterr().err


def test_main_wrong_branch(mock_release_env: Path, mocker, capsys) -> None:
    mocker.patch("shutil.which", return_value="/usr/bin/git")
    mocker.patch(
        "scripts.release.run_cmd",
        return_value=subprocess.CompletedProcess([], 0, stdout="feature-branch\n"),
    )
    with pytest.raises(SystemExit) as exc:
        release.main(["minor"])
    assert exc.value.code == 1
    assert "Releases must be cut from 'main' branch" in capsys.readouterr().err


def test_main_dirty_tree(mock_release_env: Path, mocker, capsys) -> None:
    mocker.patch("shutil.which", return_value="/usr/bin/git")

    def fake_run(cmd, **kwargs):
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="main\n")
        if cmd == ["git", "status", "--porcelain"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=" M file.py\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="")

    mocker.patch("scripts.release.run_cmd", side_effect=fake_run)
    with pytest.raises(SystemExit) as exc:
        release.main(["minor"])
    assert exc.value.code == 1
    assert "Working directory is dirty" in capsys.readouterr().err


def test_main_remote_sync_mismatch(mock_release_env: Path, mocker, capsys) -> None:
    mocker.patch("shutil.which", return_value="/usr/bin/git")

    def fake_run(cmd, **kwargs):
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="main\n")
        if cmd == ["git", "status", "--porcelain"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd == ["git", "fetch", "origin", "main", "--tags", "--quiet"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="aaaa1111\n")
        if cmd == ["git", "rev-parse", "origin/main"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="bbbb2222\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="")

    mocker.patch("scripts.release.run_cmd", side_effect=fake_run)
    with pytest.raises(SystemExit) as exc:
        release.main(["minor"])
    assert exc.value.code == 1
    assert "does not match 'origin/main'" in capsys.readouterr().err


def test_main_tag_collision_local(mock_release_env: Path, mocker, capsys) -> None:
    mocker.patch("shutil.which", return_value="/usr/bin/git")

    def fake_run(cmd, **kwargs):
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="main\n")
        if cmd == ["git", "status", "--porcelain"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd == ["git", "fetch", "origin", "main", "--tags", "--quiet"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd in (["git", "rev-parse", "HEAD"], ["git", "rev-parse", "origin/main"]):
            return subprocess.CompletedProcess(cmd, 0, stdout="aaaa1111\n")
        if cmd == ["git", "tag", "-l", "v1.1.0"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="v1.1.0\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="")

    mocker.patch("scripts.release.run_cmd", side_effect=fake_run)
    with pytest.raises(SystemExit) as exc:
        release.main(["minor"])
    assert exc.value.code == 1
    assert "Tag 'v1.1.0' already exists locally" in capsys.readouterr().err


def test_main_tag_collision_remote(mock_release_env: Path, mocker, capsys) -> None:
    mocker.patch("shutil.which", return_value="/usr/bin/git")

    def fake_run(cmd, **kwargs):
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="main\n")
        if cmd == ["git", "status", "--porcelain"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd == ["git", "fetch", "origin", "main", "--tags", "--quiet"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd in (["git", "rev-parse", "HEAD"], ["git", "rev-parse", "origin/main"]):
            return subprocess.CompletedProcess(cmd, 0, stdout="aaaa1111\n")
        if cmd == ["git", "tag", "-l", "v1.1.0"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd == ["git", "ls-remote", "--tags", "origin", "v1.1.0"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="hash refs/tags/v1.1.0\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="")

    mocker.patch("scripts.release.run_cmd", side_effect=fake_run)
    with pytest.raises(SystemExit) as exc:
        release.main(["minor"])
    assert exc.value.code == 1
    assert "Tag 'v1.1.0' already exists on remote 'origin'" in capsys.readouterr().err


def test_main_dry_run_success(mock_release_env: Path, mocker, capsys) -> None:
    mocker.patch("shutil.which", return_value="/usr/bin/git")

    def fake_run(cmd, **kwargs):
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="main\n")
        if cmd == ["git", "status", "--porcelain"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd == ["git", "fetch", "origin", "main", "--tags", "--quiet"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd in (["git", "rev-parse", "HEAD"], ["git", "rev-parse", "origin/main"]):
            return subprocess.CompletedProcess(cmd, 0, stdout="aaaa1111\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="")

    mocker.patch("scripts.release.run_cmd", side_effect=fake_run)
    release.main(["minor", "--dry-run"])

    out = capsys.readouterr().out
    assert "Candidate release version: 1.1.0 (tag: v1.1.0)" in out
    assert "Pre-flight checks passed successfully" in out

    # Verify no file mutations
    doc = tomlkit.parse(mock_release_env.read_text(encoding="utf-8"))
    assert doc["project"]["version"] == "1.0.0"


def test_main_full_release_no_push(mock_release_env: Path, mocker, capsys) -> None:
    mocker.patch("shutil.which", return_value="/usr/bin/git")
    executed_cmds = []

    def fake_run(cmd, **kwargs):
        executed_cmds.append(cmd)
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="main\n")
        if cmd == ["git", "status", "--porcelain"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd == ["git", "fetch", "origin", "main", "--tags", "--quiet"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd in (["git", "rev-parse", "HEAD"], ["git", "rev-parse", "origin/main"]):
            return subprocess.CompletedProcess(cmd, 0, stdout="aaaa1111\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="")

    mocker.patch("scripts.release.run_cmd", side_effect=fake_run)

    release.main(["minor", "--no-push"])

    # Verify pyproject.toml was mutated
    doc = tomlkit.parse(mock_release_env.read_text(encoding="utf-8"))
    assert doc["project"]["version"] == "1.1.0"

    # Verify git actions
    assert ["uv", "sync"] in executed_cmds
    assert ["git", "add", "pyproject.toml", "uv.lock"] in executed_cmds
    assert ["git", "commit", "-m", "chore: bump version to 1.1.0"] in executed_cmds
    assert [
        "git",
        "tag",
        "-a",
        "v1.1.0",
        "-m",
        "Bump version to v1.1.0",
    ] in executed_cmds
    assert not any("push" in cmd for cmd in executed_cmds)


def test_main_rollback_on_failure(mock_release_env: Path, mocker, capsys) -> None:
    mocker.patch("shutil.which", return_value="/usr/bin/git")
    executed_cmds = []

    def fake_run(cmd, **kwargs):
        executed_cmds.append(cmd)
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="main\n")
        if cmd == ["git", "status", "--porcelain"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd == ["git", "fetch", "origin", "main", "--tags", "--quiet"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd in (["git", "rev-parse", "HEAD"], ["git", "rev-parse", "origin/main"]):
            return subprocess.CompletedProcess(cmd, 0, stdout="aaaa1111\n")
        if cmd == ["git", "commit", "-m", "chore: bump version to 1.1.0"]:
            raise subprocess.CalledProcessError(1, cmd, stderr="Pre-commit hook failed")
        return subprocess.CompletedProcess(cmd, 0, stdout="")

    mocker.patch("scripts.release.run_cmd", side_effect=fake_run)

    with pytest.raises(SystemExit) as exc:
        release.main(["minor"])

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Rolling back local mutations" in err
    assert ["git", "checkout", "--", "pyproject.toml", "uv.lock"] in executed_cmds
