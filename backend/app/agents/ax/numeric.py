"""Numbers in answers: extraction, unit normalisation and the tolerance verdict (SPEC 8.2 step 4).

"4,900", "4 900", "2.8 billion", "2,800 million", "19.1%", "4.9 thousand", "2.8bn" and "2,8" are
all understood. Values are normalised to the scale of the question's `unit` ("EUR billion" ->
billions), so "2,800 million" equals 2.8.
"""

import re
from dataclasses import dataclass

EPSILON = 1e-9

_NUMBER = r"\d{1,3}(?:[,   ]\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?"
_SCALE = (
    r"(?:\s*(?P<word>trillion|billion|million|thousand|bn|mn|mln|percent|per\s?cent)\b"
    r"|(?P<sym>%|k\b|m\b|b\b))"
)
_PATTERN = re.compile(rf"(?<![\d.,])(?P<num>{_NUMBER})(?!\d)(?:{_SCALE})?", re.IGNORECASE)

_MULTIPLIER = {
    "trillion": 1e12,
    "billion": 1e9,
    "bn": 1e9,
    "b": 1e9,
    "million": 1e6,
    "mn": 1e6,
    "mln": 1e6,
    "m": 1e6,
    "thousand": 1e3,
    "k": 1e3,
    "percent": 1.0,
    "per cent": 1.0,
    "percent_sign": 1.0,
}
_UNIT_SCALES = (("trillion", 1e12), ("billion", 1e9), ("million", 1e6), ("thousand", 1e3))


@dataclass(frozen=True)
class Number:
    raw: str  # the text as written, e.g. "2.8 billion"
    value: float  # the written digits, e.g. 2.8
    multiplier: float | None  # None when no scale word followed the number
    start: int
    end: int


@dataclass(frozen=True)
class NumericAssessment:
    verdict: str  # correct | partial | wrong
    number: Number
    normalised: float
    sentence: str


def _to_float(text: str) -> float:
    text = text.replace(" ", " ").replace(" ", " ")
    if re.fullmatch(r"\d{1,3}(?:[, ]\d{3})+(?:\.\d+)?", text):
        return float(text.replace(",", "").replace(" ", ""))
    return float(text.replace(",", "."))


def extract_numbers(text: str) -> list[Number]:
    found = []
    for match in _PATTERN.finditer(text):
        word = (match.group("word") or "").lower()
        word = " ".join(word.split())
        sym = (match.group("sym") or "").lower()
        key = word or ("percent_sign" if sym == "%" else sym)
        found.append(
            Number(
                raw=match.group(0).strip(),
                value=_to_float(match.group("num")),
                multiplier=_MULTIPLIER.get(key) if key else None,
                start=match.start(),
                end=match.end(),
            )
        )
    return found


def unit_scale(unit: str | None) -> float:
    """'EUR billion' -> 1e9, 'people' -> 1."""
    lowered = (unit or "").lower()
    return next((scale for word, scale in _UNIT_SCALES if word in lowered), 1.0)


def candidates(number: Number, target_scale: float) -> list[float]:
    """Possible readings of the number in the unit's scale."""
    if number.multiplier is not None:
        return [number.value * number.multiplier / target_scale]
    readings = [number.value]
    if target_scale > 1:  # "2 800 000 000" written out in full
        readings.append(number.value / target_scale)
    return readings


def sentence_around(text: str, start: int, end: int) -> str:
    """The sentence (or line) of `text` that contains the span, copied exactly."""
    left = max(text.rfind(". ", 0, start) + 1, text.rfind("\n", 0, start) + 1, 0)
    ends = [i for i in (text.find(". ", end), text.find("\n", end)) if i != -1]
    right = min(ends) + 1 if ends else len(text)
    return text[left:right].strip()


def verdict_for(diff: float, tolerance: float) -> str:
    """Within tolerance = correct, within 2 x tolerance = partial, otherwise wrong."""
    if diff <= tolerance + EPSILON:
        return "correct"
    if tolerance > 0 and diff <= 2 * tolerance + EPSILON:
        return "partial"
    return "wrong"


def assess(
    text: str, expected: float, tolerance: float | None, unit: str | None
) -> NumericAssessment | None:
    """Judge the closest number in `text`; None when the text has no number at all."""
    target = unit_scale(unit)
    best: tuple[float, Number, float] | None = None
    for number in extract_numbers(text):
        for reading in candidates(number, target):
            diff = abs(reading - expected)
            if best is None or diff < best[0]:
                best = (diff, number, reading)
    if best is None:
        return None
    diff, number, reading = best
    return NumericAssessment(
        verdict=verdict_for(diff, tolerance or 0.0),
        number=number,
        normalised=reading,
        sentence=sentence_around(text, number.start, number.end),
    )
