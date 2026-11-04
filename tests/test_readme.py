import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")

# AC-45: section headings from the README outline (SPEC 21.1)
REQUIRED_HEADINGS = [
    "What it does",
    "Try it in 2 minutes",
    "Connect your own API",
    "Scheduling",
    "How data is transformed",
    "Security",
    "Design decisions",
    "Development",
    "Roadmap",
    "License",
]


@pytest.mark.parametrize("heading", REQUIRED_HEADINGS)
def test_required_heading_present(heading):
    # A heading may add words after the name, such as "(demo mode, no API key)".
    pattern = rf"^## {re.escape(heading)}\b.*$"
    assert re.search(pattern, README, flags=re.MULTILINE), heading


def _local_image_paths():
    paths = []
    for match in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)\)", README):
        paths.append(match.group(1))
    for match in re.finditer(r'<img[^>]+src="([^"]+)"', README):
        paths.append(match.group(1))
    return [p for p in paths if not re.match(r"^[a-z]+://", p)]


def test_every_local_image_exists():
    for relative in _local_image_paths():
        assert (ROOT / relative).is_file(), relative


def test_license_file_names_the_holder():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in text
    assert "Copyright (c) 2026 api-automation-tool contributors" in text


def test_ci_workflow_matrix_matches_spec():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "ubuntu-latest" in text and "windows-latest" in text
    assert '"3.11"' in text and '"3.12"' in text
    assert "pip install -c constraints.txt -e" in text
    assert "ruff check ." in text
    assert "ruff format --check ." in text
    assert "pytest -q" in text
