import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


def get_pypi_sdist(package: str, version: str) -> tuple[str, str]:
    """Queries PyPI for the sdist URL and SHA256 of a specific dependency."""
    url = f"https://pypi.org/pypi/{package}/{version}/json"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as e:
        sys.exit(f"Failed to fetch PyPI metadata for {package}=={version}: {e}")

    for info in data.get("urls", []):
        if info.get("packagetype") == "sdist":
            return str(info["url"]), str(info["digests"]["sha256"])

    sys.exit(f"No sdist found for {package}=={version} on PyPI.")


def run_cmd(args: list[str], cwd: Path | None = None) -> str:
    """Executes a shell command and returns its standard output."""
    try:
        res = subprocess.run(args, capture_output=True, text=True, check=True, cwd=cwd)
        return res.stdout
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {' '.join(args)}", file=sys.stderr)
        print(f"Stdout: {e.stdout}", file=sys.stderr)
        print(f"Stderr: {e.stderr}", file=sys.stderr)
        raise


def splice_formula(
    formula_path: Path, new_url: str, new_sha: str, resource_text: str
) -> None:
    """Splice File Content for a Homebrew formula."""
    content = formula_path.read_text(encoding="utf-8")

    content = re.sub(
        r'^  url\s+".*"', f'  url "{new_url}"', content, flags=re.MULTILINE, count=1
    )
    content = re.sub(
        r'^  sha256\s+".*"',
        f'  sha256 "{new_sha}"',
        content,
        flags=re.MULTILINE,
        count=1,
    )

    pattern = r"(?<=# RESOURCE_BLOCK_START\n).*?(?=# RESOURCE_BLOCK_END)"
    replacement = f"{resource_text}\n  " if resource_text else "  "
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)

    formula_path.write_text(content, encoding="utf-8")
