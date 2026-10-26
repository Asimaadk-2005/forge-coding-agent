"""Domain logic for Space Fractions.

No UI imports. Exact arithmetic via fractions.Fraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
import re
import uuid

DECIMAL_TOLERANCE: Fraction = Fraction(1, 1_000_000_000)  # 1e-9

_NUMBER_RE = re.compile(
    r"^\s*"
    r"(?P<sign>[+-]?)"
    r"(?:(?P<whole>\d+)\s+(?P<whole_num>\d+)\s*/\s*(?P<whole_den>\d+)"
    r"|(?P<frac_num>\d+)\s*/\s*(?P<frac_den>\d+)"
    r"|(?P<int>\d+)"
    r"|(?P<dec>\d*\.\d+)"
    r"|(?P<dec_int>\d+\.\d*))"
    r"\s*$"
)


@dataclass(frozen=True)
class Question:
    """A single educational question."""

    id: str
    prompt: str
    answer: Fraction
    explanation: str = ""


def _apply_sign(sign: str, value: Fraction) -> Fraction:
    """Apply matched sign without discarding it."""
    if sign == "-":
        return -value
    return value


def parse_answer(text: str) -> Fraction:
    """Parse signed mixed numbers, simple fractions, integers, and finite decimals.

    Raises ValueError for malformed input or zero denominators.
    Preserves the sign in every branch.
    """
    if not isinstance(text, str):
        raise ValueError("Answer must be text")

    match = _NUMBER_RE.match(text)
    if not match:
        raise ValueError("Malformed number")

    sign = match.group("sign") or ""

    if match.group("whole_den") is not None:
        whole = int(match.group("whole"))
        numerator = int(match.group("whole_num"))
        denominator = int(match.group("whole_den"))
        if denominator == 0:
            raise ValueError("Zero denominator")
        value = Fraction(whole * denominator + numerator, denominator)
        return _apply_sign(sign, value)

    if match.group("frac_den") is not None:
        numerator = int(match.group("frac_num"))
        denominator = int(match.group("frac_den"))
        if denominator == 0:
            raise ValueError("Zero denominator")
        value = Fraction(numerator, denominator)
        return _apply_sign(sign, value)

    if match.group("int") is not None:
        value = Fraction(int(match.group("int")), 1)
        return _apply_sign(sign, value)

    if match.group("dec") is not None:
        decimal_text = match.group("dec")
        if decimal_text.startswith("."):
            decimal_text = "0" + decimal_text
        value = Fraction(decimal_text)
        return _apply_sign(sign, value)

    if match.group("dec_int") is not None:
        decimal_text = match.group("dec_int")
        if decimal_text.endswith("."):
            decimal_text = decimal_text[:-1]
        value = Fraction(decimal_text)
        return _apply_sign(sign, value)

    # Unreachable given the regex alternation.
    raise ValueError("Malformed number")


def check_answer(answer: Fraction, text: str) -> bool:
    """Return True if text matches answer exactly or within decimal tolerance.

    Fraction inputs (containing '/') require exact equality.
    Decimal inputs may use the 1e-9 tolerance.
    """
    try:
        candidate = parse_answer(text)
    except (ValueError, ZeroDivisionError):
        return False

    if '/' in text:
        return candidate == answer

    difference = abs(candidate - answer)
    return difference <= DECIMAL_TOLERANCE


class Session:
    """Tracks progression through a list of questions and score state."""

    def __init__(self, questions: list[Question]) -> None:
        if not questions:
            raise ValueError("Session requires at least one question")
        self.questions: list[Question] = list(questions)
        self.index: int = 0
        self.correct: int = 0
        self.attempted: int = 0
        self.answered: bool = False
        self.finished: bool = False

    def current(self) -> Question | None:
        """Return the current question or None if finished."""
        if self.finished or self.index >= len(self.questions):
            return None
        return self.questions[self.index]

    def submit(self, text: str) -> tuple[bool, str]:
        """Score the current question exactly once.

        Malformed input does not consume an attempt.
        Returns (correct: bool, message: str).
        """
        if self.finished:
            raise AssertionError("Session finished")
        if self.answered:
            raise AssertionError("Question already answered")
        question = self.current()
        if question is None:
            self.finished = True
            raise AssertionError("Session finished")

        try:
            parsed = parse_answer(text)
        except (ValueError, ZeroDivisionError):
            return False, "Malformed answer"

        correct = check_answer(question.answer, text)
        self.answered = True
        self.attempted += 1
        if correct:
            self.correct += 1
        return correct, ("Correct" if correct else "Incorrect")

    def next(self) -> Question | None:
        """Advance exactly once only after a valid submission."""
        if not self.answered:
            return None
        self.answered = False
        self.index += 1
        if self.index >= len(self.questions):
            self.finished = True
            return None
        return self.questions[self.index]

    @property
    def accuracy(self) -> int:
        """Return accuracy as a rounded percentage 0..100."""
        if self.attempted == 0:
            return 0
        return round((self.correct / self.attempted) * 100)


def make_score_record(session: Session) -> dict:
    """Create a score record with unique id, totals, accuracy, and ISO timestamp."""
    total = len(session.questions)
    return {
        "id": str(uuid.uuid4()),
        "correct": session.correct,
        "total": total,
        "accuracy": session.accuracy,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }