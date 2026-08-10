import hashlib
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts import update_homebrew_local


def test_get_sha256(mocker):
    mock_content = b"fake-tarball-content"
    expected_hash = hashlib.sha256(mock_content).hexdigest()

    mock_response = MagicMock()
    mock_response.read.side_effect = [mock_content, b""]

    mock_urlopen = mocker.patch("urllib.request.urlopen")
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = update_homebrew_local.get_sha256("https://fake-url.com")

    assert result == expected_hash
    mock_urlopen.assert_called_once()


def test_main_happy_path(mocker, tmp_path):
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

    mocker.patch("scripts.update_homebrew_local.get_sha256", return_value="new_sha_123")

    def mock_get_pypi_sdist(pkg, version):
        return f"https://pypi.org/{pkg}.tar.gz", f"sha_{pkg}"

    mocker.patch(
        "scripts.update_homebrew_local.get_pypi_sdist", side_effect=mock_get_pypi_sdist
    )

    def mock_run_cmd(args, cwd=None):
        if "export" in args:
            output_file = Path(args[args.index("-o") + 1])
            output_file.write_text(
                "markdownify==0.11.0 ; python_version >= '3.8'\nbeautifulsoup4==4.12.3",
                encoding="utf-8",
            )
        return ""

    mocker.patch("scripts.update_homebrew_local.run_cmd", side_effect=mock_run_cmd)

    update_homebrew_local.main()

    result = formula_path.read_text(encoding="utf-8")

    assert (
        'url "https://github.com/JacksonFergusonDev/focal/archive/refs/tags/v0.1.0.tar.gz"'
        in result
    )
    assert 'sha256 "new_sha_123"' in result

    # Verifies multiple blocks, correct indentation, and ignoring the environment marker
    assert (
        '  # RESOURCE_BLOCK_START\n  resource "markdownify" do\n    url "https://pypi.org/markdownify.tar.gz"\n    sha256 "sha_markdownify"\n  end\n\n  resource "beautifulsoup4" do\n    url "https://pypi.org/beautifulsoup4.tar.gz"\n    sha256 "sha_beautifulsoup4"\n  end\n  # RESOURCE_BLOCK_END'
        in result
    )

    assert not (caller_dir / "reqs.txt").exists()


def test_get_sha256_error(mocker):
    mock_urlopen = mocker.patch("urllib.request.urlopen")
    mock_urlopen.side_effect = urllib.error.URLError("Not found")

    with pytest.raises(SystemExit, match="Error fetching tarball"):
        update_homebrew_local.get_sha256("https://fake-url.com")


def test_main_missing_formula(mocker, tmp_path):
    caller_dir = tmp_path / "caller"
    caller_dir.mkdir()

    mocker.patch(
        "sys.argv",
        [
            "update_homebrew_local.py",
            "--repo",
            "JacksonFergusonDev/focal",
            "--tag",
            "v0.1.0",
            "--formula",
            str(tmp_path / "missing.rb"),
            "--caller-dir",
            str(caller_dir),
        ],
    )
    with pytest.raises(SystemExit, match="Formula not found"):
        update_homebrew_local.main()


def test_main_missing_caller_dir(mocker, tmp_path):
    formula_path = tmp_path / "formula.rb"
    formula_path.touch()

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
            str(tmp_path / "missing"),
        ],
    )
    with pytest.raises(SystemExit, match="Caller directory not found"):
        update_homebrew_local.main()
