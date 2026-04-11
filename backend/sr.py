"""
TradePass — SuperMemo-2 (SM-2) Implementation.
Fields match schema/database.sql specification.
SM-2 quality grades: 0=blackout, 1=wrong, 2=hard, 3=okay, 4=good, 5=perfect
"""
from datetime import date, timedelta
from dataclasses import dataclass


@dataclass
class SM2Fields:
    easiness_factor: float  # EF, min 1.3
    interval: int           # days until next review
    repetitions: int        # successful review count


def quality_to_grade(quality: int) -> int:
    """Normalise user-facing 0-5 quality input to SM-2 grade."""
    return max(0, min(5, quality))


def sm2_step(fields: SM2Fields, quality: int) -> SM2Fields:
    """
    Apply one SM-2 review to the current SR fields.
    Returns updated SM2Fields.
    """
    q = quality_to_grade(quality)
    ef = fields.easiness_factor
    rep = fields.repetitions
    interval = fields.interval

    if q < 3:
        # Failed — reset repetitions, interval = 1
        rep = 0
        interval = 1
    else:
        # Passed
        if rep == 0:
            interval = 1
        elif rep == 1:
            interval = 6
        else:
            interval = round(interval * ef)

        rep += 1

    # Update easiness factor
    ef = ef + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    ef = max(1.3, ef)

    next_review = date.today() + timedelta(days=interval)

    return SM2Fields(
        easiness_factor=round(ef, 3),
        interval=interval,
        repetitions=rep,
    )


def grade_from_answer(user_answer_index: int, correct_answer_index: int) -> int:
    """
    Map a user's answer and known correct answer to an SM-2 quality grade.
    For binary correct/incorrect: correct=4 (good), incorrect=1 (wrong).
    """
    return 4 if user_answer_index == correct_answer_index else 1
