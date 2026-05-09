#!/usr/bin/env python3
"""Synchronizes a Homebrew formula using a local uv manifest.

Extracts the sdist URL and SHA256 hash from a GitHub release tarball,
updates the Homebrew formula file, parses the caller's dependencies via
`uv export`, directly fetches PyPI sdist vectors, and splices
those resources into the formula using specified sentinels.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


def get_sha256(url: str) -> str:
    """Fetches a file over HTTP and returns its SHA256 checksum."""
    print(f"Fetching {url}...")
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as response:
            return hashlib.sha256(response.read()).hexdigest()
    except urllib.error.URLError as e:
        sys.exit(f"Error fetching tarball: {e}")


def get_pypi_sdist(package: str, version: str) -> tuple[str, str]:
    """Queries PyPI for the sdist URL and SHA256 of a specific package version."""
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
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description="Sync Homebrew formula locally.")
    parser.add_argument(
        "--repo", required=True, help="GitHub repository (e.g., owner/repo)"
    )
    parser.add_argument("--tag", required=True, help="Release tag (e.g., v0.1.0)")
    parser.add_argument("--formula", type=Path, required=True, help="Path to formula")
    parser.add_argument(
        "--caller-dir", type=Path, required=True, help="Caller repo root"
    )
    args = parser.parse_args()

    formula_path: Path = args.formula.resolve()
    caller_dir: Path = args.caller_dir.resolve()

    if not formula_path.exists():
        sys.exit(f"Formula not found: {formula_path}")
    if not caller_dir.exists():
        sys.exit(f"Caller directory not found: {caller_dir}")

    # 1. Resolve Root URL and Hash
    tarball_url = f"https://github.com/{args.repo}/archive/refs/tags/{args.tag}.tar.gz"
    new_sha = get_sha256(tarball_url)

    # 2. Export strict local dependencies
    print(f"Exporting local dependencies from {caller_dir}...")
    reqs_file = caller_dir / "reqs.txt"
    run_cmd(
        [
            "uv",
            "export",
            "--no-dev",
            "--no-hashes",
            "--format",
            "requirements-txt",
            "-o",
            "reqs.txt",
        ],
        cwd=caller_dir,
    )

    # 3. Parse requirements and query PyPI directly (Bypassing poet entirely)
    print("Resolving PyPI resource blocks...")
    resource_blocks = []

    with open(reqs_file, encoding="utf-8") as f:
        for line in f:
            # Strip environment markers (e.g., ; python_version >= '3.9')
            line = line.split(";")[0].strip()

            # Skip comments and flags
            if not line or line.startswith("#") or line.startswith("-"):
                continue

            if "==" in line:
                pkg, version = line.split("==")
                pkg = pkg.strip()
                version = version.strip()

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

    # 4. Splice File Content
    content = formula_path.read_text(encoding="utf-8")

    # Update Root
    content = re.sub(
        r'^  url\s+".*"', f'  url "{tarball_url}"', content, flags=re.MULTILINE, count=1
    )
    content = re.sub(
        r'^  sha256\s+".*"',
        f'  sha256 "{new_sha}"',
        content,
        flags=re.MULTILINE,
        count=1,
    )

    # Update Resources
    pattern = r"(?<=# RESOURCE_BLOCK_START\n).*?(?=# RESOURCE_BLOCK_END)"
    # Add trailing padding if there are resources, otherwise just padding
    replacement = f"{resource_text}\n  " if resource_text else "  "
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)

    formula_path.write_text(content, encoding="utf-8")

    # Clean up
    reqs_file.unlink(missing_ok=True)

    print("Successfully synchronized formula.")


if __name__ == "__main__":
    main()
