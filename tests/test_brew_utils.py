import json
import subprocess
import urllib.error
from unittest.mock import MagicMock

import pytest

from scripts import brew_utils


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

    url, sha = brew_utils.get_pypi_sdist("markdownify", "0.11.0")

    assert url == "https://sdist-url.tar.gz"
    assert sha == "abc12345"


def test_get_pypi_sdist_http_error(mocker):
    mock_urlopen = mocker.patch("urllib.request.urlopen")
    mock_urlopen.side_effect = urllib.error.URLError("Not found")

    with pytest.raises(SystemExit, match="Failed to fetch PyPI metadata"):
        brew_utils.get_pypi_sdist("markdownify", "0.11.0")


def test_get_pypi_sdist_missing(mocker):
    mock_payload = {"urls": [{"packagetype": "bdist_wheel"}]}
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(mock_payload).encode("utf-8")

    mock_urlopen = mocker.patch("urllib.request.urlopen")
    mock_urlopen.return_value.__enter__.return_value = mock_response

    with pytest.raises(SystemExit, match="No sdist found"):
        brew_utils.get_pypi_sdist("markdownify", "0.11.0")


def test_run_cmd_success(mocker):
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(stdout="success output\n")

    result = brew_utils.run_cmd(["echo", "hello"])
    assert result == "success output\n"
    mock_run.assert_called_once_with(
        ["echo", "hello"], capture_output=True, text=True, check=True, cwd=None
    )


def test_run_cmd_failure(mocker, capsys):
    mock_run = mocker.patch("subprocess.run")
    mock_run.side_effect = subprocess.CalledProcessError(
        1, ["false"], output="out", stderr="err"
    )

    with pytest.raises(subprocess.CalledProcessError):
        brew_utils.run_cmd(["false"])

    captured = capsys.readouterr()
    assert "Command failed: false" in captured.err
    assert "Stdout: out" in captured.err
    assert "Stderr: err" in captured.err


def test_splice_formula(tmp_path):
    formula_path = tmp_path / "formula.rb"
    formula_path.write_text(
        'class Test < Formula\n  url "old_url"\n  sha256 "old_sha"\n  # RESOURCE_BLOCK_START\n  # RESOURCE_BLOCK_END\nend',
        encoding="utf-8",
    )

    brew_utils.splice_formula(
        formula_path,
        "new_url",
        "new_sha",
        '  resource "dep" do\n    url "dep_url"\n    sha256 "dep_sha"\n  end',
    )

    content = formula_path.read_text(encoding="utf-8")
    assert 'url "new_url"' in content
    assert 'sha256 "new_sha"' in content
    assert 'resource "dep" do' in content
