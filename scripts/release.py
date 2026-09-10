# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "tomlkit>=0.15.1",
# ]
# ///

"""Standalone release orchestration script for uv-based Python projects.

Executes a two-phase release workflow:
1. Phase 1 (Pre-Flight): Read-only validations (clean working tree, branch guard,
   remote sync check, dry-run SemVer computation, local & remote tag collision checks).
2. Phase 2 (Transactional Execution): Atomically updates pyproject.toml, updates lockfile,
   creates release commit, creates annotated tag, and atomically pushes to remote,
   with automated rollback if any step fails or is interrupted.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

import tomlkit

SEMVER_RE = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


def get_clean_env() -> dict[str, str]:
    """Return an environment stripped of uv's internal script virtualenv variables."""
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    env.pop("PYTHONHOME", None)
    return env


def run_cmd(
    cmd: list[str],
    *,
    capture: bool = True,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a system command and return the completed process."""
    if env is None:
        env = get_clean_env()
    try:
        return subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            check=check,
            env=env,
        )
    except subprocess.CalledProcessError as e:
        if capture:
            if e.stdout:
                sys.stdout.write(e.stdout)
            if e.stderr:
                sys.stderr.write(e.stderr)
        raise


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Atomically writes text content to a file via a temporary file swap."""
    file_descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temp_path = Path(temp_name)

    try:
        with os.fdopen(file_descriptor, "w", encoding=encoding) as temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)
    except Exception:
        with suppress(OSError):
            temp_path.unlink()
        raise


def compute_bumped_version(current_version: str, part: str) -> str:
    """Computes the incremented semantic version."""
    match = SEMVER_RE.match(str(current_version))
    if not match:
        raise ValueError(f"Current version '{current_version}' is not valid SemVer.")

    major = int(match["major"])
    minor = int(match["minor"])
    patch = int(match["patch"])

    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"

    raise ValueError(f"Invalid version part: '{part}'. Choose major, minor, or patch.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse release command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Safely cuts an atomic release for uv-based Python projects."
    )
    parser.add_argument(
        "part", choices=["major", "minor", "patch"], help="The version part to bump"
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="The expected release branch (default: main).",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="The git remote name (default: origin).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate pre-flight checks and preview the candidate version without making changes.",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Commit and tag locally without pushing to remote.",
    )
    parser.add_argument(
        "--pre-flight",
        action="append",
        default=[],
        dest="pre_flight_cmds",
        help="Optional shell command to execute during pre-flight checks (can be specified multiple times).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Main release orchestration routine."""
    args = parse_args(argv)

    # --------------------------------------------------
    # Phase 1: Pre-Flight Checks (Strictly Read-Only)
    # --------------------------------------------------
    print("=== [Pre-Flight 1/6] Checking tool prerequisites ===")
    for tool in ("git", "uv"):
        if not shutil.which(tool):
            print(f"Error: Required tool '{tool}' not found in PATH.", file=sys.stderr)
            sys.exit(1)

    print("=== [Pre-Flight 2/6] Verifying release branch ===")
    try:
        branch_res = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        current_branch = branch_res.stdout.strip()
    except subprocess.CalledProcessError:
        print("Error: Failed to determine current git branch.", file=sys.stderr)
        sys.exit(1)

    if current_branch != args.branch:
        print(
            f"Error: Releases must be cut from '{args.branch}' branch (currently on '{current_branch}').",
            file=sys.stderr,
        )
        sys.exit(1)

    print("=== [Pre-Flight 3/6] Checking for uncommitted or untracked changes ===")
    status_res = run_cmd(["git", "status", "--porcelain"])
    if status_res.stdout.strip():
        print(
            "Error: Working directory is dirty. Please commit, stash, or clean all changes first:\n",
            file=sys.stderr,
        )
        sys.stderr.write(status_res.stdout)
        sys.exit(1)

    print("=== [Pre-Flight 4/6] Checking synchronization with remote ===")
    try:
        run_cmd(["git", "fetch", args.remote, args.branch, "--tags", "--quiet"])
        local_hash = run_cmd(["git", "rev-parse", "HEAD"]).stdout.strip()
        remote_hash = run_cmd(
            ["git", "rev-parse", f"{args.remote}/{args.branch}"]
        ).stdout.strip()
    except subprocess.CalledProcessError as e:
        print(
            f"Error: Failed to check remote synchronization with '{args.remote}/{args.branch}': {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    if local_hash != remote_hash:
        print(
            f"Error: Local branch '{args.branch}' ({local_hash[:8]}) does not match "
            f"'{args.remote}/{args.branch}' ({remote_hash[:8]}).\n"
            "Please pull or push changes before releasing.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("=== [Pre-Flight 5/6] Validating pyproject.toml & SemVer ===")
    pyproject_path = Path("pyproject.toml")
    if not pyproject_path.exists():
        print("Error: pyproject.toml not found in working directory.", file=sys.stderr)
        sys.exit(1)

    try:
        raw_text = pyproject_path.read_text(encoding="utf-8")
        doc = tomlkit.parse(raw_text)
        current_version = str(doc["project"]["version"])
        new_version = compute_bumped_version(current_version, args.part)
    except Exception as e:
        print(
            f"Error reading or calculating version from pyproject.toml: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    new_tag = f"v{new_version}"
    print(f"Current version: {current_version}")
    print(f"Candidate release version: {new_version} (tag: {new_tag})")

    print("=== [Pre-Flight 6/6] Checking for tag collisions ===")
    local_tag_check = run_cmd(["git", "tag", "-l", new_tag]).stdout.strip()
    if local_tag_check:
        print(f"Error: Tag '{new_tag}' already exists locally.", file=sys.stderr)
        sys.exit(1)

    remote_tag_check = run_cmd(
        ["git", "ls-remote", "--tags", args.remote, new_tag]
    ).stdout.strip()
    if remote_tag_check:
        print(
            f"Error: Tag '{new_tag}' already exists on remote '{args.remote}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Run optional custom pre-flight commands
    for cmd in args.pre_flight_cmds:
        print(f"=== Running pre-flight command: {cmd} ===")
        try:
            subprocess.run(cmd, shell=True, check=True, env=get_clean_env())
        except subprocess.CalledProcessError as e:
            print(
                f"Error: Pre-flight command '{cmd}' failed with code {e.returncode}.",
                file=sys.stderr,
            )
            sys.exit(1)

    if args.dry_run:
        print(
            f"\n✔ Pre-flight checks passed successfully. Candidate version is {new_version} (dry-run)."
        )
        return

    # --------------------------------------------------
    # Phase 2: Transactional Execution & Rollback Guard
    # --------------------------------------------------
    print(f"\n=== Executing release mutations for {new_tag} ===")
    initial_rev = local_hash

    tag_created = False
    commit_created = False
    files_mutated = False

    def rollback() -> None:
        print(
            "\n⚠ Release failed mid-flight! Rolling back local mutations...",
            file=sys.stderr,
        )
        if tag_created:
            run_cmd(["git", "tag", "-d", new_tag], check=False)
        if commit_created:
            run_cmd(["git", "reset", "--hard", initial_rev], check=False)
        elif files_mutated:
            run_cmd(["git", "checkout", "--", "pyproject.toml", "uv.lock"], check=False)
        print(
            f"✔ Rollback complete. Repository cleanly restored to {initial_rev[:8]}.",
            file=sys.stderr,
        )

    try:
        # 1. Mutate pyproject.toml
        print(f"Updating pyproject.toml to version {new_version}...")
        doc["project"]["version"] = new_version
        atomic_write_text(pyproject_path, tomlkit.dumps(doc))
        files_mutated = True

        # 2. Synchronize lockfile
        print("Updating lockfile via uv sync...")
        run_cmd(["uv", "sync"], capture=False)
        run_cmd(["uv", "lock", "--check"], capture=False)

        # 3. Stage and commit
        print(f"Creating release commit for {new_version}...")
        run_cmd(["git", "add", "pyproject.toml", "uv.lock"])
        run_cmd(["git", "commit", "-m", f"chore: bump version to {new_version}"])
        commit_created = True

        # 4. Create annotated tag
        print(f"Creating annotated tag {new_tag}...")
        run_cmd(["git", "tag", "-a", new_tag, "-m", f"Bump version to {new_tag}"])
        tag_created = True

        # 5. Push atomically to remote
        if not args.no_push:
            print(f"Atomically shipping commit and {new_tag} to {args.remote}...")
            run_cmd(
                ["git", "push", args.remote, "HEAD", "--tags", "--atomic"],
                capture=False,
            )
        else:
            print(
                f"Skipping push (--no-push flag active). Local tag {new_tag} created."
            )

        print(f"\n✔ Successfully released {new_tag}!")

    except (KeyboardInterrupt, Exception) as e:
        rollback()
        if isinstance(e, KeyboardInterrupt):
            print("Release aborted by user.", file=sys.stderr)
            sys.exit(130)
        print(f"Release failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
