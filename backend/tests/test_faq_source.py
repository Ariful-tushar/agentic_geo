"""Tests for safe, idempotent updates to the demo FAQ source page."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.faq_source import add_public_question

SOURCE = """<html>
<body>
  <ul>
    <li><span class="question">Existing water question?</span></li>
  </ul>
</body>
</html>
"""


def test_add_question_escapes_html_and_inserts_at_top(tmp_path: Path) -> None:
    page = tmp_path / "questions.html"
    page.write_text(SOURCE, encoding="utf-8")

    added = add_public_question("How can <water> reuse help?", page)

    content = page.read_text(encoding="utf-8")
    assert added is True
    assert content.index("&lt;water&gt;") < content.index("Existing water question?")
    assert "<water>" not in content
    assert 'class="question">How can &lt;water&gt; reuse help?</span>' in content


def test_add_question_is_idempotent_after_html_decoding_and_normalization(tmp_path: Path) -> None:
    page = tmp_path / "questions.html"
    page.write_text(SOURCE, encoding="utf-8")

    assert add_public_question("Existing water question!", page) is False
    assert page.read_text(encoding="utf-8") == SOURCE


@pytest.mark.parametrize("question", ["short", "x" * 301])
def test_add_question_rejects_invalid_length(tmp_path: Path, question: str) -> None:
    page = tmp_path / "questions.html"
    page.write_text(SOURCE, encoding="utf-8")

    with pytest.raises(ValidationError):
        add_public_question(question, page)
    assert page.read_text(encoding="utf-8") == SOURCE


def test_add_question_reports_missing_list_marker(tmp_path: Path) -> None:
    page = tmp_path / "questions.html"
    page.write_text("<html></html>", encoding="utf-8")

    with pytest.raises(ValueError, match="expected question-list marker"):
        add_public_question("A valid water treatment question?", page)

