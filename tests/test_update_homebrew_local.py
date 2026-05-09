import hashlib
from unittest.mock import MagicMock

import pytest

from scripts import update_homebrew_local


def test_get_sha256(mocker):
    """Verifies that the SHA256 hashing correctly processes a byte stream."""
    mock_content = b"fake-tarball-content"
    expected_hash = hashlib.sha256(mock_content).hexdigest()

    mock_response = MagicMock()
    mock_response.read.return_value = mock_content

    mock_urlopen = mocker.patch("urllib.request.urlopen")
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = update_homebrew_local.get_sha256("https://fake-url.com")

    assert result == expected_hash
    mock_urlopen.assert_called_once()


def test_run_cmd(mocker):
    """Verifies subprocess execution and standard output capturing."""
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(returncode=0, stdout="mocked output\n")

    result = update_homebrew_local.run_cmd(["uv", "version"])

    assert result == "mocked output\n"
    mock_run.assert_called_once_with(
        ["uv", "version"], capture_output=True, text=True, check=True, cwd=None
    )


def test_main_happy_path(mocker, tmp_path):
    """End-to-end integration test verifying file mutation and cleanup."""
    # 1. Setup sandboxed file system
    formula_path = tmp_path / "test_formula.rb"
    formula_path.write_text(
        "class TestCLI < Formula\n"
        '  url "old_url"\n'
        '  sha256 "old_sha"\n'
        "  # RESOURCE_BLOCK_START\n"
        "  # RESOURCE_BLOCK_END\n"
        "end",
        encoding="utf-8",
    )

    caller_dir = tmp_path / "caller_repo"
    caller_dir.mkdir()

    # 2. Mock CLI Arguments
    mocker.patch(
        "sys.argv",
        [
            "update_homebrew_local.py",
            "--repo",
            "JacksonFergusonDev/focal",
            "--tag",
            "v0.1.0",
            "--formula",
            str(formula_path),
            "--caller-dir",
            str(caller_dir),
        ],
    )

    # 3. Mock Network & Subprocess IO
    mocker.patch("scripts.update_homebrew_local.get_sha256", return_value="new_sha_123")

    def mock_run_cmd(args, cwd=None):
        if "export" in args:
            # Simulate uv export creating the reqs file
            (caller_dir / "reqs.txt").write_text(
                "markdownify==0.11.0", encoding="utf-8"
            )
            return ""
        if "poet" in args:
            # Simulate poet stdout
            return 'resource "markdownify" do\n  url "https://files..."\n  sha256 "abc"\nend'
        return ""

    mocker.patch("scripts.update_homebrew_local.run_cmd", side_effect=mock_run_cmd)

    # 4. Execute Main Pipeline
    update_homebrew_local.main()

    # 5. Assertions
    result = formula_path.read_text(encoding="utf-8")

    # Verify root url/sha replacement
    assert (
        'url "https://github.com/JacksonFergusonDev/focal/archive/refs/tags/v0.1.0.tar.gz"'
        in result
    )
    assert 'sha256 "new_sha_123"' in result

    # Verify resource splicing and RuboCop-compliant indentation
    assert (
        '  # RESOURCE_BLOCK_START\n  resource "markdownify" do\n    url "https://files..."\n    sha256 "abc"\n  end\n  # RESOURCE_BLOCK_END'
        in result
    )

    # Verify ephemeral manifest cleanup
    assert not (caller_dir / "reqs.txt").exists()


def test_main_missing_formula_aborts(mocker, tmp_path):
    """Verifies the pipeline safely aborts if the formula file is missing."""
    caller_dir = tmp_path / "caller"
    caller_dir.mkdir()

    mocker.patch(
        "sys.argv",
        [
            "update_homebrew_local.py",
            "--repo",
            "test/repo",
            "--tag",
            "v1",
            "--formula",
            str(tmp_path / "does_not_exist.rb"),
            "--caller-dir",
            str(caller_dir),
        ],
    )

    with pytest.raises(SystemExit) as e:
        update_homebrew_local.main()

    assert "Formula not found" in str(e.value)
