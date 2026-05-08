<!-- markdownlint-disable-file MD041 -->
<div align="center">

# CI/CD Tooling

[![CI](https://img.shields.io/github/actions/workflow/status/JacksonFergusonDev/ci-cd-tooling/ci.yml?style=flat-square&color=white&labelColor=black&label=CI)](https://github.com/JacksonFergusonDev/ci-cd-tooling/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.14+-white?style=flat-square&color=white&labelColor=black)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/badge/style-ruff-white?style=flat-square&color=white&labelColor=black)](https://github.com/astral-sh/ruff)
[![Mypy](https://img.shields.io/badge/mypy-checked-white?style=flat-square&color=white&labelColor=black)](https://mypy-lang.org/)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-white?style=flat-square&color=white&labelColor=black)](https://github.com/pre-commit/pre-commit)
[![License](https://img.shields.io/badge/license-MIT-white?style=flat-square&color=white&labelColor=black)](LICENSE)

</div>

Centralized infrastructure repository for reusable GitHub Actions workflows and deployment automation scripts. By decoupling pipeline logic from application code, this repository acts as a single source of truth to eliminate CI/CD duplication across projects.

## Reusable Workflows

### Homebrew Tap Updater (`update-homebrew.yml`)

Automates the synchronization of a Homebrew formula with a newly published PyPI release. It polls PyPI for the target version, extracts the source distribution checksum, and dynamically synthesizes Python dependency resources via `homebrew-pypi-poet`.

**Caller Workflow Implementation:**

To invoke this workflow from a dependent repository, append the following job to your release pipeline:

```yaml
  sync-homebrew:
    name: Delegate Homebrew Update
    needs: build-n-publish # Ensure PyPI publish completes first
    uses: JacksonFergusonDev/ci-cd-tooling/.github/workflows/update-homebrew.yml@main
    with:
      tag: ${{ github.ref_name }}
      package_name: "target-package"
      formula_path: "Formula/target-package.rb"
    secrets:
      TAP_GITHUB_TOKEN: ${{ secrets.TAP_GITHUB_TOKEN }}
```
