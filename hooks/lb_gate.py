#!/usr/bin/env python3
"""MOVED to lasergear/lb_gate.py on 2026-07-27.

A shim, not a copy. A copy is what this whole day was about: two files that must agree,
with nothing making them agree, is a divergence waiting to be found months later. So
anything still wired to the old path fails HERE and says where to look, instead of quietly
running a hook that has stopped receiving fixes.

The split: laserbrain is the logic, lasermind is the protocol, laserfield is the server,
and lasergear is the INSTRUCTIONS — when to invoke the instrument, and what to do with a
verdict. These three are instructions. They lived in lasermind only because the instruction
layer had no name yet, and a thing with no name gets put down wherever someone was
standing.
"""
import sys

sys.exit(
    'lb_gate moved to lasergear/lb_gate.py on 2026-07-27 — the instruction layer got its '
    'own home. Update the path in ~/.claude/settings.json.'
)
