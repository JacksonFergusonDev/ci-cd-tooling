#!/usr/bin/env python3
"""Synchronizes a Homebrew formula using a local uv manifest.

Extracts the sdist URL and SHA256 hash from a GitHub release tarball,
updates the Homebrew formula file, dynamically generates Python dependency
resources using `poet` against the local caller repository, and splices
those resources into the formula using specified sentinels.
"""

import argparse
import hashlib
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


def run_cmd(args: list[str], cwd: Path | None = None) -> str:
    """Executes a shell command and returns its standard output."""
    res = subprocess.run(args, capture_output=True, text=True, check=True, cwd=cwd)
    return res.stdout


def main() -> None:
    """Execute the Homebrew formula synchronization pipeline."""
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

    # 1. Resolve URL and Hash dynamically via the --repo argument
    tarball_url = f"https://github.com/{args.repo}/archive/refs/tags/{args.tag}.tar.gz"
    new_sha = get_sha256(tarball_url)

    # 2. Generate Python Dependencies using uv in the caller directory
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

    print("Generating poet resources...")
    raw_resources = run_cmd(
        ["uv", "run", "--with", "homebrew-pypi-poet", "poet", "-f", "reqs.txt"],
        cwd=caller_dir,
    )

    # 3. Format Ruby Blocks
    formatted_blocks = []
    for line in raw_resources.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Outer wrapper elements get 2 spaces (formula class scope)
        if stripped.startswith("resource ") or stripped == "end":
            formatted_blocks.append(f"  {stripped}")
        # Inner properties (url, sha256, etc.) get 4 spaces
        else:
            formatted_blocks.append(f"    {stripped}")

    resource_text = "\n".join(formatted_blocks)

    # 4. Splice File Content
    content = formula_path.read_text(encoding="utf-8")

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

    pattern = r"(?<=# RESOURCE_BLOCK_START\n).*?(?=# RESOURCE_BLOCK_END)"
    replacement = f"{resource_text}\n  " if resource_text else "  "
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)

    formula_path.write_text(content, encoding="utf-8")

    # Clean up the ephemeral requirements file
    reqs_file.unlink(missing_ok=True)

    print("Successfully synchronized formula.")


if __name__ == "__main__":
    main()
