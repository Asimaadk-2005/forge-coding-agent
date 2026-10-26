"""Domain logic for Space Fractions.

Pure Python/Fraction/Tkinter-free module.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from fractions import Fraction
from typing import Optional


_DECIMAL_RE = re.compile(
    r"^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?$"
)
_MIXED_RE = re.compile(
    r"^[+-]?\s*(\d+)\s+(\d+)\s*/\s*(\d+)$"
)
_FRACTION_RE = re.compile(
    r"^[+-]?\s*(\d+)\s*/\s*(\d+)$"
)

_TOLERANCE = Fraction(1, 1_000_000_000)


@dataclass(frozen=True)
class Question:
    id: str
    prompt: str
    answer: Fraction
    explanation: str = ""


def parse_answer(text: str) -> Fraction:
    """Parse a signed integer, decimal, mixed number, or fraction.

    Raises ValueError for malformed input and zero denominators.
    The decimal branch accepts ordinary finite decimal notation such as
    ``0.333333333``; scientific notation is accepted by the finite-decimal
    parser, and is converted exactly by Fraction.
    """
    if not isinstance(text, str):
        raise ValueError("Answer must be text")
    value = text.strip()
    if not value:
        raise ValueError("Answer is empty")

    mixed = _MIXED_RE.match(value)
    if mixed:
        whole, numerator, denominator = mixed.groups()
        denom = int(denominator)
        if denom == 0:
            raise ValueError("Zero denominator")
        result = Fraction(int(whole)) + Fraction(int(numerator), denom)
        if value.lstrip()[0] == "-":
            result = -result
        return result

    fraction = _FRACTION_RE.match(value)
    if fraction:
        numerator, denominator = fraction.groups()
        denom = int(denominator)
        if denom == 0:
            raise ValueError("Zero denominator")
        return Fraction(int(numerator), denom)

    if _DECIMAL_RE.match(value):
        return Fraction(value)

    raise ValueError("Malformed number")


def _fraction_close(left: Fraction, right: Fraction) -> bool:
    difference = left - right
    if difference < 0:
        difference = -difference
    return difference <= _TOLERANCE


def check_answer(answer: Fraction, text: str) -> bool:
    """Return True when *text* matches *answer*.

    Exact fraction equality is used first.  A finite decimal acceptable
    answer is then compared with an absolute tolerance of 1e-9 without
    converting either side to float.  Fraction inputs (containing '/') are
    compared exactly only.
    """
    try:
        submitted = parse_answer(text)
    except (ValueError, ZeroDivisionError):
        return False
    if submitted == answer:
        return True
    # Only apply decimal tolerance when the submitted text is a decimal
    # (no '/' character). Fraction inputs must match exactly.
    if '/' in text:
        return False
    return _fraction_close(submitted, answer)


def format_decimal(answer: Fraction, digits: int = 12) -> str:
    """Render a Fraction as a finite decimal with *digits* fractional digits.

    The ``Fraction`` constructor accepts a float string exactly, so this is
    safe for UI and test display even when the value would overflow ``float``.
    """
    sign = "-" if answer < 0 else ""
    value = abs(answer)
    numerator = value.numerator
    denominator = value.denominator
    scale = 10 ** digits
    whole, remainder = divmod(numerator * scale, denominator)
    fractional = str(remainder).zfill(digits)
    return f"{sign}{whole}.{fractional}"


class Session:
    """One play-through over a fixed question list.

    Each question may be submitted only once.  Malformed answers are rejected
    before scoring and therefore do not consume an attempt.  A valid wrong
    answer consumes the attempt.
    """

    def __init__(self, questions: list[Question]):
        if not questions:
            raise ValueError("Session requires at least one question")
        self.questions: list[Question] = list(questions)
        self.index: int = 0
        self.correct: int = 0
        self.attempted: int = 0
        self.answered: bool = False

    @property
    def finished(self) -> bool:
        return self.index >= len(self.questions)

    @property
    def accuracy(self) -> float:
        if not self.questions:
            return 0.0
        return round((self.correct / len(self.questions)) * 100, 1)

    def current(self) -> Optional[Question]:
        if self.finished:
            return None
        return self.questions[self.index]

    def submit(self, text: str) -> tuple[bool, str]:
        """Score the current question exactly once.

        Returns ``(correct, message)``.  Malformed text returns
        ``(False, message)`` and leaves ``answered`` False and
        ``attempted`` unchanged.
        """
        question = self.current()
        if question is None:
            return False, "No question is active"
        if self.answered:
            return False, "Answer already submitted for this question"

        try:
            submitted = parse_answer(text)
        except (ValueError, ZeroDivisionError):
            return False, "Enter a valid fraction or decimal answer"

        self.attempted += 1
        self.answered = True
        correct = check_answer(question.answer, text)
        if correct:
            self.correct += 1
            return True, "Correct!"
        return False, (
            f"Incorrect. The correct answer is "
            f"{format_decimal(question.answer)}"
            + (f"\n{question.explanation}" if question.explanation else "")
        )

    def next(self) -> Optional[Question]:
        """Advance exactly one question only after a submission."""
        if not self.answered:
            raise RuntimeError("Submit an answer before advancing")
        self.index += 1
        self.answered = False
        return self.current()