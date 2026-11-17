from quiz.norm import normalize_answer


def test_trims_both_sides():
    assert normalize_answer("  Paris ") == "paris"
