from colors.clamp import clamp


def test_clamp():
    assert clamp(100, 0, 255) == 100
    assert clamp(-5, 0, 255) == 0
    assert clamp(300, 0, 255) == 255
