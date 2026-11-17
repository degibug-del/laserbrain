from decimal import ROUND_HALF_UP, Decimal

from .norm import normalize_answer


def grade(answers, key):
    correct = sum(
        1 for qid, right in key.items()
        if answers.get(qid) is not None and normalize_answer(answers[qid]) == normalize_answer(right)
    )
    total = len(key)
    if not total:
        return {"correct": 0, "total": 0, "percent": 0}
    pct = (Decimal(correct) * 100 / Decimal(total)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return {"correct": correct, "total": total, "percent": int(pct)}
