from anagrams import group


def test_groups_in_order():
    assert group(["listen", "silent", "enlist", "google", "inlets"]) == [
        ["listen", "silent", "enlist", "inlets"], ["google"]]


def test_case_insensitive():
    assert group(["Tea", "eat", "Ate", "tan"]) == [["Tea", "eat", "Ate"], ["tan"]]
