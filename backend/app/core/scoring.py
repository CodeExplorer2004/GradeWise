import math

SCORE_INCREMENT = 0.5


def quantize_score(value: float) -> float:
    """Round a score to the nearest supported half-point increment."""
    return round(value / SCORE_INCREMENT) * SCORE_INCREMENT


def has_valid_score_increment(value: float) -> bool:
    """Return whether a finite score is an integer or ends in .5."""
    return math.isfinite(value) and math.isclose(
        value / SCORE_INCREMENT,
        round(value / SCORE_INCREMENT),
        abs_tol=1e-9,
    )
