import json
from unittest.mock import MagicMock

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
