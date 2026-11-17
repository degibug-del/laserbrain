from slots import free_slots


def test_one_meeting():
    assert free_slots([("10:00", "11:00")], "09:00", "17:00", 30) == [("09:00", "10:00"), ("11:00", "17:00")]


def test_unsorted_overlapping():
    busy = [("13:00", "14:00"), ("10:00", "12:00"), ("11:30", "12:30")]
    assert free_slots(busy, "09:00", "17:00", 20) == [
        ("09:00", "10:00"), ("12:30", "13:00"), ("14:00", "17:00")]
