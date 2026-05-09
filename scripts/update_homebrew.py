#!/usr/bin/env python3
"""Synchronizes a Homebrew formula with a newly published PyPI release.

This script polls PyPI for visibility of a specific version, extracts the
root sdist URL and SHA256 hash, dynamically resolves the dependency tree
using `uv pip compile`, fetches sdist vectors for all dependencies directly
from PyPI, and splices the formula using specified sentinels.
"""

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def get_pypi_metadata(
    package_name: str, version: str, max_retries: int = 60, delay: int = 2
) -> dict[str, Any]:
    """Poll PyPI until the specified package version metadata becomes available."""
    url = f"https://pypi.org/pypi/{package_name}/{version}/json"
    print(f"Polling {url} for release visibility...")

    for _ in range(max_retries):
        try:
            with urllib.request.urlopen(url) as response:
                if response.status == 200:
                    data = response.read().decode("utf-8")
                    return json.loads(data)  # type: ignore[no-any-return]
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print(f"HTTP Error querying PyPI: {e.code}", file=sys.stderr)

        time.sleep(delay)

    raise TimeoutError(f"Timed out waiting for {package_name} {version} on PyPI.")


def extract_sdist_info(metadata: dict[str, Any]) -> tuple[str, str]:
    """Parse the PyPI metadata payload for the source distribution details."""
    for url_info in metadata.get("urls", []):
        if url_info.get("packagetype") == "sdist":
            return str(url_info["url"]), str(url_info["digests"]["sha256"])

    raise ValueError("sdist information not found in PyPI metadata.")


def get_pypi_sdist(package: str, version: str) -> tuple[str, str]:
    """Queries PyPI for the sdist URL and SHA256 of a specific dependency."""
    url = f"https://pypi.org/pypi/{package}/{version}/json"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as response:
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


def main() -> None:
    """Execute the Homebrew formula synchronization pipeline."""
    parser = argparse.ArgumentParser(
        description="Update Homebrew formula with newly published PyPI releases."
    )
    parser.add_argument("--version", required=True, help="Version tag (e.g., 0.7.0).")
    parser.add_argument(
        "--formula-path",
        type=Path,
        required=True,
        help="Path to the Ruby formula file.",
    )
    parser.add_argument(
        "--package",
        default="protostar",
        help="Target PyPI package name.",
    )
    args = parser.parse_args()

    # Strip 'v' prefix if present to ensure PyPI API compatibility
    args.version = args.version.lstrip("v")

    formula_path: Path = args.formula_path.resolve()
    if not formula_path.exists():
        sys.exit(f"Error: Formula file not found at {formula_path}")

    # 1. Wait for registry sync
    metadata = get_pypi_metadata(args.package, args.version)

    # 2. Extract root distribution vectors
    new_url, new_sha = extract_sdist_info(metadata)
    print(f"Resolved root sdist:\n  URL: {new_url}\n  SHA: {new_sha}")

    # 3. Resolve the dependency tree via uv pip compile
    print("Resolving dependency tree...")
    reqs_in = Path("reqs.in")
    reqs_txt = Path("reqs.txt")
    reqs_in.write_text(f"{args.package}=={args.version}", encoding="utf-8")

    run_cmd(
        [
            "uv",
            "pip",
            "compile",
            "--no-annotate",
            "--no-header",
            str(reqs_in),
            "-o",
            str(reqs_txt),
        ]
    )

    # 4. Parse requirements and query PyPI directly
    print("Resolving PyPI resource blocks...")
    resource_blocks = []

    with open(reqs_txt, encoding="utf-8") as f:
        for line in f:
            # Strip environment markers (e.g., ; python_version >= '3.9')
            line = line.split(";")[0].strip()

            if not line or line.startswith("#") or line.startswith("-"):
                continue

            if "==" in line:
                pkg, version = line.split("==")
                pkg = pkg.strip()
                version = version.strip()

                # Excise the root package to pass Homebrew audits
                if pkg.lower() == args.package.lower():
                    continue

                print(f"  -> Fetching {pkg}=={version}")
                sdist_url, sdist_sha = get_pypi_sdist(pkg, version)

                block = (
                    f'  resource "{pkg}" do\n'
                    f'    url "{sdist_url}"\n'
                    f'    sha256 "{sdist_sha}"\n'
                    f"  end"
                )
                resource_blocks.append(block)

    resource_text = "\n\n".join(resource_blocks)

    # 5. Splice File Content
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

    # Clean up ephemeral compilation files
    reqs_in.unlink(missing_ok=True)
    reqs_txt.unlink(missing_ok=True)

    print("Successfully synchronized formula.")


if __name__ == "__main__":
    main()
