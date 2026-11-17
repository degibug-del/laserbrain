from handles.wordlist import load_words


def test_load_words(tmp_path):
    p = tmp_path / "w.txt"
    p.write_text("# comment\nAlpha\n\n  beta  \n")
    assert load_words(p) == ["alpha", "beta"]
