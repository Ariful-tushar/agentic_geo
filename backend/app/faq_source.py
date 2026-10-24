"""Update the demo FAQ source page from an admin-submitted question."""

import html
import os
import sys
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

from app.agents.faq.text import normalise_question
from app.schemas.api import PublicQuestionIn

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PAGE = REPO_ROOT / "frontend" / "public" / "demo" / "public-questions.html"
SOURCE_PAGE_URL = "https://answerwatch-jade.vercel.app/demo/public-questions.html"
LIST_START = "  <ul>\n"


class _QuestionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.questions: list[str] = []
        self._inside_question = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = dict(attrs).get("class", "") or ""
        if tag == "span" and "question" in classes.split():
            self._inside_question = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._inside_question:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._inside_question:
            self.questions.append("".join(self._parts))
            self._inside_question = False


def add_public_question(question: str, path: Path = SOURCE_PAGE) -> bool:
    """Add one escaped question at the top of the source page; return False for a duplicate."""
    validated = PublicQuestionIn(text=question)
    text = validated.text
    source = path.read_text(encoding="utf-8")
    parser = _QuestionParser()
    parser.feed(source)
    normalized = normalise_question(text)
    if any(normalise_question(existing) == normalized for existing in parser.questions):
        return False
    if LIST_START not in source:
        raise ValueError("The FAQ source page has no expected question-list marker.")

    today = datetime.now(UTC).date()
    item = (
        f'    <li><time datetime="{today.isoformat()}">{today.strftime("%d %b %Y")}</time>'
        f'<span class="question">{html.escape(text)}</span></li>\n'
    )
    path.write_text(source.replace(LIST_START, LIST_START + item, 1), encoding="utf-8")
    return True


def main() -> int:
    question = os.environ.get("FAQ_QUESTION")
    if not question:
        print("FAQ_QUESTION environment variable is required.", file=sys.stderr)
        return 2
    try:
        added = add_public_question(question)
    except (OSError, ValueError) as exc:
        print(f"Could not update the FAQ source page: {exc}", file=sys.stderr)
        return 1
    print("Question added to the FAQ source page." if added else "Question already exists.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
