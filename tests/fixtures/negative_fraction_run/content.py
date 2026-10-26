from domain import Question
from fractions import Fraction

TITLE = "Space Fractions"
SUBTITLE = "Sixth-Grade Fraction Mission"

HELP_TEXT = (
    "Welcome, Cadet!\n\n"
    "Your mission is to solve fraction problems and guide your rocket "
    "through the galaxy.\n\n"
    "HOW TO PLAY:\n"
    "• Read the problem shown on the mission screen.\n"
    "• Type your answer as a fraction (3/4), mixed number (1 1/2), "
    "or decimal (0.75).\n"
    "• Click CHECK to submit your answer.\n"
    "• Click NEXT to advance to the next problem.\n"
    "• Watch your rocket rise with each correct answer!\n\n"
    "SCORING:\n"
    "• Each problem is scored once.\n"
    "• Decimal answers must be within 0.000000001 of the exact value.\n"
    "• Your final accuracy appears on the results screen.\n\n"
    "ADMIN MODE:\n"
    "• Add, edit, or delete practice problems.\n"
    "• At least one problem must remain.\n\n"
    "Good luck, Commander!"
)


def default_questions() -> list[Question]:
    """Return at least 20 unique valid questions across four operations."""
    return [
        Question(
            "q001",
            "1/2 + 1/4 = ?",
            Fraction(3, 4),
            "Find a common denominator: 2/4 + 1/4 = 3/4.",
        ),
        Question(
            "q002",
            "1/3 + 1/6 = ?",
            Fraction(1, 2),
            "Convert 1/3 to 2/6, then add: 2/6 + 1/6 = 3/6 = 1/2.",
        ),
        Question(
            "q003",
            "3/4 - 1/2 = ?",
            Fraction(1, 4),
            "Convert 1/2 to 2/4, then subtract: 3/4 - 2/4 = 1/4.",
        ),
        Question(
            "q004",
            "2/3 - 1/6 = ?",
            Fraction(1, 2),
            "Convert 2/3 to 4/6, then subtract: 4/6 - 1/6 = 3/6 = 1/2.",
        ),
        Question(
            "q005",
            "5/8 + 1/8 = ?",
            Fraction(3, 4),
            "Same denominator: 5/8 + 1/8 = 6/8 = 3/4.",
        ),
        Question(
            "q006",
            "7/10 - 2/5 = ?",
            Fraction(3, 10),
            "Convert 2/5 to 4/10, then subtract: 7/10 - 4/10 = 3/10.",
        ),
        Question(
            "q007",
            "1/2 × 3/4 = ?",
            Fraction(3, 8),
            "Multiply numerators and denominators: (1×3)/(2×4) = 3/8.",
        ),
        Question(
            "q008",
            "2/3 × 3/5 = ?",
            Fraction(2, 5),
            "Multiply numerators and denominators: (2×3)/(3×5) = 6/15 = 2/5.",
        ),
        Question(
            "q009",
            "3/4 ÷ 1/2 = ?",
            Fraction(3, 2),
            "Multiply by the reciprocal: 3/4 × 2/1 = 6/4 = 3/2.",
        ),
        Question(
            "q010",
            "5/6 ÷ 2/3 = ?",
            Fraction(5, 4),
            "Multiply by the reciprocal: 5/6 × 3/2 = 15/12 = 5/4.",
        ),
        Question(
            "q011",
            "1 1/2 + 1/4 = ?",
            Fraction(7, 4),
            "Convert 1 1/2 to 6/4, then add: 6/4 + 1/4 = 7/4.",
        ),
        Question(
            "q012",
            "2 1/3 + 1/6 = ?",
            Fraction(5, 2),
            "Convert 2 1/3 to 14/6, then add: 14/6 + 1/6 = 15/6 = 5/2.",
        ),
        Question(
            "q013",
            "1 3/4 - 2/3 = ?",
            Fraction(13, 12),
            "Convert to twelfths: 21/12 - 8/12 = 13/12.",
        ),
        Question(
            "q014",
            "2 1/2 - 1 1/4 = ?",
            Fraction(5, 4),
            "Convert to fourths: 10/4 - 5/4 = 5/4.",
        ),
        Question(
            "q015",
            "1 1/2 × 2/3 = ?",
            Fraction(1, 1),
            "Convert 1 1/2 to 3/2, multiply: (3×2)/(2×3) = 6/6 = 1.",
        ),
        Question(
            "q016",
            "2 1/4 ÷ 3/4 = ?",
            Fraction(3, 1),
            "Convert 2 1/4 to 9/4, multiply by reciprocal: 9/4 × 4/3 = 36/12 = 3.",
        ),
        Question(
            "q017",
            "-1/2 + 3/4 = ?",
            Fraction(1, 4),
            "Convert -1/2 to -2/4, then add: -2/4 + 3/4 = 1/4.",
        ),
        Question(
            "q018",
            "-2/3 - 1/6 = ?",
            Fraction(-5, 6),
            "Convert -2/3 to -4/6, then subtract: -4/6 - 1/6 = -5/6.",
        ),
        Question(
            "q019",
            "-3/4 × 2/5 = ?",
            Fraction(-3, 10),
            "Multiply numerators and denominators: (-3×2)/(4×5) = -6/20 = -3/10.",
        ),
        Question(
            "q020",
            "-5/8 ÷ 1/2 = ?",
            Fraction(-5, 4),
            "Multiply by the reciprocal: -5/8 × 2/1 = -10/8 = -5/4.",
        ),
        Question(
            "q021",
            "1/5 + 3/10 = ?",
            Fraction(1, 2),
            "Convert 1/5 to 2/10, then add: 2/10 + 3/10 = 5/10 = 1/2.",
        ),
        Question(
            "q022",
            "4/9 - 1/3 = ?",
            Fraction(1, 9),
            "Convert 1/3 to 3/9, then subtract: 4/9 - 3/9 = 1/9.",
        ),
        Question(
            "q023",
            "3/7 × 7/9 = ?",
            Fraction(1, 3),
            "Multiply numerators and denominators: (3×7)/(7×9) = 21/63 = 1/3.",
        ),
        Question(
            "q024",
            "6/11 ÷ 3/11 = ?",
            Fraction(2, 1),
            "Multiply by the reciprocal: 6/11 × 11/3 = 66/33 = 2.",
        ),
    ]