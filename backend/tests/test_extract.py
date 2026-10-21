from datetime import date
from pathlib import Path

from app.fetch.extract import extract

SAMPLE = (Path(__file__).parent / "fixtures" / "sample_page.html").read_text(encoding="utf-8")


def test_extracts_title_h1_and_main_text_only() -> None:
    page = extract(SAMPLE)
    assert page.title == "About us | Example Oy"
    assert page.h1 == "About us"
    assert "4,900 employees" in page.text
    assert "Jane Doe" in page.text
    for noise in ("Menu", "Cookie", "tracking", "color: red"):
        assert noise not in page.text


def test_published_date_wins_over_modified() -> None:
    page = extract(SAMPLE)
    assert (page.published_date, page.date_kind) == (date(2025, 3, 14), "published")


def test_modified_date_from_json_ld() -> None:
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@graph": [{"dateModified": "2024-02-03T10:00:00Z"}]}'
        "</script></head><body><p>x</p></body></html>"
    )
    page = extract(html)
    assert (page.published_date, page.date_kind) == (date(2024, 2, 3), "modified")


def test_time_tag_counts_as_published() -> None:
    page = extract('<body><time datetime="2023-11-05">5 Nov</time><p>x</p></body>')
    assert (page.published_date, page.date_kind) == (date(2023, 11, 5), "published")


def test_last_modified_header_is_the_last_resort() -> None:
    page = extract("<body><p>x</p></body>", "Wed, 21 Oct 2015 07:28:00 GMT")
    assert (page.published_date, page.date_kind) == (date(2015, 10, 21), "modified")


def test_no_date_information_gives_none() -> None:
    page = extract("<body><p>x</p></body>")
    assert (page.published_date, page.date_kind) == (None, None)


def test_page_without_main_uses_body() -> None:
    assert "hello" in extract("<html><body><div>hello</div></body></html>").text
