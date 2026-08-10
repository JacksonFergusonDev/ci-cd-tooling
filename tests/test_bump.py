from pathlib import Path

import pytest
import tomlkit

from scripts import bump


def test_atomic_write_text(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    content = "test content"

    bump.atomic_write_text(target, content)

    assert target.exists()
    assert target.read_text(encoding="utf-8") == content


@pytest.fixture
def mock_pyproject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Creates a temporary pyproject.toml and sets the working directory to it."""
    toml_content = """
[project]
name = "test-project"
version = "1.2.3"
"""
    project_file = tmp_path / "pyproject.toml"
    project_file.write_text(toml_content, encoding="utf-8")

    # Change working directory so Path("pyproject.toml") naturally resolves here
    monkeypatch.chdir(tmp_path)
    return project_file


@pytest.mark.parametrize(
    ("part", "expected_version"),
    [
        ("major", "2.0.0"),
        ("minor", "1.3.0"),
        ("patch", "1.2.4"),
    ],
)
def test_main_bump_logic(
    mock_pyproject: Path, mocker, capsys, part: str, expected_version: str
) -> None:
    mocker.patch("sys.argv", ["bump.py", part])

    bump.main()

    # Check stdout
    captured = capsys.readouterr()
    assert captured.out.strip() == expected_version

    # Check TOML mutation
    doc = tomlkit.parse(mock_pyproject.read_text(encoding="utf-8"))
    assert doc["project"]["version"] == expected_version


def test_main_invalid_args(mocker, capsys) -> None:
    mocker.patch("sys.argv", ["bump.py", "invalid"])

    with pytest.raises(SystemExit) as e:
        bump.main()

    assert e.value.code == 2
    captured = capsys.readouterr()
    assert "usage: bump.py" in captured.err


def test_main_missing_pyproject(
    mocker, capsys, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Change to an empty directory to simulate a missing pyproject.toml
    monkeypatch.chdir(tmp_path)
    mocker.patch("sys.argv", ["bump.py", "patch"])

    with pytest.raises(SystemExit) as e:
        bump.main()

    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Error: pyproject.toml not found." in captured.err


def test_main_missing_version_key(mock_pyproject: Path, mocker, capsys) -> None:
    mock_pyproject.write_text('[project]\nname = "test-project"\n')
    mocker.patch("sys.argv", ["bump.py", "patch"])

    with pytest.raises(SystemExit) as e:
        bump.main()

    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Key [project.version] missing" in captured.err
