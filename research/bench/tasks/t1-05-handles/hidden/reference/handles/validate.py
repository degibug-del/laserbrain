import pathlib
import re

from .wordlist import load_words

RESERVED_FILE = pathlib.Path(__file__).with_name("reserved.txt")
_ALLOWED = re.compile(r"[a-z0-9_]+")


def validate(name):
    problems = []
    if not 3 <= len(name) <= 20:
        problems.append("length")
    if not _ALLOWED.fullmatch(name):
        problems.append("chars")
    if name[:1].isdigit():
        problems.append("leading_digit")
    if name.lower() in set(load_words(RESERVED_FILE)):
        problems.append("reserved")
    return problems
