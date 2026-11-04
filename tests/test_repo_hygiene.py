"""AC-46: repository hygiene. Git is required; the test is skipped without it.

This file is exempt from its own scan because it names the forbidden strings.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GIT = shutil.which("git")
SELF = "tests/test_repo_hygiene.py"

pytestmark = pytest.mark.skipif(GIT is None, reason="git is not on PATH")

TEST_ONLY = ["super-secret", "query-secret", "zz-secret", "ENTIRE_TOKEN"]
FORBIDDEN = [*TEST_ONLY, "BEGIN PRIVATE KEY", "ghp_", "github_pat_"]

# Strings removed from a file before it is checked, per the AC-46 exception list
# (amended by owner decision, Escalation 2, 2026-11-04).
# docs/ACCEPTANCE.md quotes the rule text, where the three secret-format strings appear in
# backticks. Only those backticked quotes are removed there, so a bare leaked token still fails.
RULE_TEXT = ["BEGIN PRIVATE KEY", "ghp_", "github_pat_"]
EXCEPTIONS = {
    "docs/PLAN.md": ["ENTIRE_TOKEN_STORE"],
    "docs/REVIEW.md": TEST_ONLY,
    "docs/ACCEPTANCE.md": [*TEST_ONLY, *(f"`{s}`" for s in RULE_TEXT)],
}
TESTS_EXCEPTIONS = TEST_ONLY

GITIGNORE_EXPECTED = [
    ".venv/",
    "__pycache__/",
    "*.pyc",
    ".pytest_cache/",
    ".ruff_cache/",
    "*.egg-info/",
    "build/",
    "dist/",
    "data/",
    "ops/",
    "video/",
    ".env",
    "*.log",
    "book-log.txt",
]

DEMO_CREDENTIALS = ["demo-key-123", "demo-token-456", "demo-pass"]
DEMO_CREDENTIAL_HOMES = ("src/apitool/demo/", "tests/", "docs/", "README.md")


def _tracked():
    result = subprocess.run([GIT, "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [line for line in result.stdout.splitlines() if line]


def _read(relative):
    try:
        return (ROOT / relative).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None  # not a text file


def _strip_for(relative):
    if relative in EXCEPTIONS:
        return EXCEPTIONS[relative]
    if relative.startswith("tests/"):
        return TESTS_EXCEPTIONS
    return []


def test_no_tracked_data_ops_video_or_binary_artifacts():
    bad = [
        path
        for path in _tracked()
        if path.startswith(("data/", "ops/", "video/"))
        or path.endswith((".db", ".xlsx", ".csv", ".log"))
    ]
    assert bad == []


def test_no_tracked_text_file_contains_a_forbidden_string():
    failures = []
    for path in _tracked():
        if path == SELF:
            continue
        text = _read(path)
        if text is None:
            continue
        for token in _strip_for(path):
            text = text.replace(token, "")
        for forbidden in FORBIDDEN:
            if forbidden in text:
                failures.append(f"{path}: {forbidden}")
    assert failures == []


def test_gitignore_matches_spec_line_for_line():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines == GITIGNORE_EXPECTED


def test_demo_credentials_only_in_allowed_places():
    failures = []
    for path in _tracked():
        if path == SELF or path.startswith(DEMO_CREDENTIAL_HOMES):
            continue
        text = _read(path)
        if text is None:
            continue
        for credential in DEMO_CREDENTIALS:
            if credential in text:
                failures.append(f"{path}: {credential}")
    assert failures == []
