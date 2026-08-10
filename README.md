<!-- markdownlint-disable-file MD041 -->
<div align="center">

# CI/CD Tooling

[![CI](https://img.shields.io/github/actions/workflow/status/JacksonFergusonDev/ci-cd-tooling/ci.yml?style=flat-square&color=white&labelColor=black&label=CI)](https://github.com/JacksonFergusonDev/ci-cd-tooling/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.13+-white?style=flat-square&color=white&labelColor=black)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/badge/style-ruff-white?style=flat-square&color=white&labelColor=black)](https://github.com/astral-sh/ruff)
[![Mypy](https://img.shields.io/badge/mypy-checked-white?style=flat-square&color=white&labelColor=black)](https://mypy-lang.org/)
[![prek](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/j178/prek/master/docs/assets/badge-v0.json&style=flat-square&color=white&labelColor=black)](https://github.com/j178/prek)
[![License](https://img.shields.io/badge/license-MIT-white?style=flat-square&color=white&labelColor=black)](LICENSE)

</div>

Centralized infrastructure repository for reusable GitHub Actions workflows and deployment automation scripts. By decoupling pipeline logic and release management from application code, this repository acts as a single source of truth across projects.

---

## 🛠 Repository Contents

```text
.
├── .github/workflows/
│   ├── ci.yml                     # Internal verification pipeline
│   ├── update-homebrew.yml        # Reusable workflow for PyPI-published packages
│   └── update-homebrew-local.yml  # Reusable workflow using caller repository manifests
├── scripts/
│   ├── bump.py                    # Standalone SemVer version bumping tool
│   ├── update_homebrew.py         # PyPI polling & Homebrew formula dependency splicing
│   └── update_homebrew_local.py   # Manifest-based Homebrew formula dependency splicing
└── tests/
    ├── test_bump.py               # Unit tests for SemVer mutation logic
    └── test_update_homebrew_local.py
```

---

## 🔄 Reusable Workflows

### 1. Homebrew Tap Updater (`update-homebrew.yml`)

Automates synchronization of a Homebrew formula when releasing a package published to PyPI. It polls PyPI until the release is visible, extracts the source distribution checksum, resolves the full dependency tree via `uv pip compile`, and splices Python resources directly into the target Ruby formula before running `brew audit`.

**Caller Workflow Usage:**

```yaml
jobs:
  sync-homebrew:
    name: Delegate Homebrew Update
    needs: build-n-publish # Ensure PyPI publishing succeeds first
    uses: JacksonFergusonDev/ci-cd-tooling/.github/workflows/update-homebrew.yml@main
    with:
      tag: ${{ github.ref_name }}
      package_name: "target-package"
      formula_path: "Formula/target-package.rb"
    secrets:
      TAP_GITHUB_TOKEN: ${{ secrets.TAP_GITHUB_TOKEN }}
```

### 2. Local Manifest Homebrew Tap Updater (`update-homebrew-local.yml`)

Designed for projects that do not publish source distributions directly to PyPI or rely on local manifest exports (e.g., using `uv export`). Extracts release tarball checksums directly from GitHub releases, builds local dependency blocks, and commits the updated formula to your tap repository.

**Caller Workflow Usage:**

```yaml
jobs:
  sync-homebrew-local:
    name: Sync Local Homebrew Formula
    needs: release
    uses: JacksonFergusonDev/ci-cd-tooling/.github/workflows/update-homebrew-local.yml@main
    with:
      tag: ${{ github.ref_name }}
      formula_path: "Formula/target-cli.rb"
    secrets:
      TAP_GITHUB_TOKEN: ${{ secrets.TAP_GITHUB_TOKEN }}
```

---

## 📜 Automation Scripts & Remote Execution

All scripts inside `scripts/` are standalone Python scripts featuring [PEP 723](https://peps.python.org/pep-0723/) inline metadata blocks. They can be executed directly via `uv run` without manually cloning this repository or installing dependencies locally.

### Semantic Version Bumper (`scripts/bump.py`)

Atomically updates the `[project.version]` string in a `pyproject.toml` file according to Semantic Versioning (`major`, `minor`, or `patch`).

#### Remote Usage in `justfile` or Shell

You can execute the script directly from GitHub's raw endpoint:

```bash
uv run https://raw.githubusercontent.com/JacksonFergusonDev/ci-cd-tooling/refs/heads/main/scripts/bump.py patch
```

Example `justfile` integration:

```bash
bump part:
    #!/usr/bin/env bash
    NEW_VERSION=$(uv run https://raw.githubusercontent.com/JacksonFergusonDev/ci-cd-tooling/refs/heads/main/scripts/bump.py {{ part }})
    git add pyproject.toml
    git commit -m "chore: bump version to $NEW_VERSION"
    git tag -a "v$NEW_VERSION" -m "Release v$NEW_VERSION"
```
