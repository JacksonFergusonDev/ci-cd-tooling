import hashlib
import json
from unittest.mock import MagicMock

from scripts import update_homebrew_local


def test_get_sha256(mocker):
    mock_content = b"fake-tarball-content"
    expected_hash = hashlib.sha256(mock_content).hexdigest()

    mock_response = MagicMock()
    mock_response.read.return_value = mock_content

    mock_urlopen = mocker.patch("urllib.request.urlopen")
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = update_homebrew_local.get_sha256("https://fake-url.com")

    assert result == expected_hash
    mock_urlopen.assert_called_once()


def test_get_pypi_sdist(mocker):
    mock_payload = {
        "urls": [
            {
                "packagetype": "bdist_wheel",
                "url": "wheel_url",
                "digests": {"sha256": "wrong"},
            },
            {
                "packagetype": "sdist",
                "url": "https://sdist-url.tar.gz",
                "digests": {"sha256": "abc12345"},
            },
        ]
    }
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(mock_payload).encode("utf-8")

    mock_urlopen = mocker.patch("urllib.request.urlopen")
    mock_urlopen.return_value.__enter__.return_value = mock_response

    url, sha = update_homebrew_local.get_pypi_sdist("markdownify", "0.11.0")

    assert url == "https://sdist-url.tar.gz"
    assert sha == "abc12345"


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
            (caller_dir / "reqs.txt").write_text(
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
