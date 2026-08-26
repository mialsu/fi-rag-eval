"""The one thing worth asserting before any pipeline exists: the package is importable.

This is not a placeholder. It is the assertion the build gate leans on — that a clean
`uv sync --locked` produces an environment where `fi_rag_eval` imports.
"""

import fi_rag_eval


def test_package_imports_and_reports_a_version() -> None:
    assert fi_rag_eval.__version__
