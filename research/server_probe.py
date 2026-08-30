#!/usr/bin/env python3
"""Drive the real MCP server over stdio. Shared by the conformance tests.

WHY THIS EXISTS

Three tests used to reach into mcp-server.mjs with regexes and eval the fragments they
pulled out — `const _STOP = new Set([...` up to the next brace, then `new Function(...)` on
the result. It worked until someone inserted a function between `_STOP` and `toWords`, at
which point the non-greedy match stopped covering `toWords` and every one of those tests
exited 2 with "could not extract".

They then stayed red without anyone noticing, which is the part that matters. Those tests
are what guarantee the JS server and the Python SDK tokenize identically — and `context_id`
is an FNV-1a hash over sorted normalized tokens that is supposed to be byte-identical
across Python, JS and TS. A divergence would silently split one context into two, and for
some number of days nothing was checking.

So: no more scraping. These helpers start the server the way a host starts it and ask it
questions over the wire. That is strictly better than importing the module, because it
tests the thing agents actually talk to, including the dispatch layer — and it cannot go
stale when code moves around inside the file, because it depends on the published tool
contract rather than on source layout.

The server's own normalizer is readable straight off `check_state`: `laserscore` is
`⟨tokens, sorted, |-joined⟩ progress dN`, which is the canonical form the grammar
documents. No private function needs extracting at all.
"""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

SERVER = pathlib.Path(__file__).resolve().parent / 'mcp-server.mjs'


class Server:
    """A running mcp-server.mjs, talked to over stdio. Use as a context manager."""

    def __init__(self, env=None):
        self._extra = env or {}
        self._n = 1

    def __enter__(self):
        if not shutil.which('node'):
            raise RuntimeError('node not found')
        if not SERVER.exists():
            raise RuntimeError(f'no server at {SERVER}')
        # An isolated drift log per probe. Without it a conformance run appends dozens of
        # synthetic readings to the real corpus, and the corpus is evidence.
        self._td = tempfile.mkdtemp(prefix='lb-probe-')
        env = dict(os.environ,
                   LASERBRAIN_DRIFT_LOG=str(pathlib.Path(self._td) / 'drift.jsonl'),
                   LASERBRAIN_AGENT='conformance-probe',
                   **self._extra)
        self.p = subprocess.Popen(
            ['node', str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, env=env)
        self._send({'jsonrpc': '2.0', 'id': self._next(), 'method': 'initialize',
                    'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                               'clientInfo': {'name': 'conformance', 'version': '1'}}})
        self.p.stdout.readline()
        self._send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        return self

    def __exit__(self, *exc):
        try:
            self.p.terminate()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()
        shutil.rmtree(self._td, ignore_errors=True)
        return False

    def _next(self):
        self._n += 1
        return self._n

    def _send(self, obj):
        self.p.stdin.write(json.dumps(obj) + '\n')
        self.p.stdin.flush()

    def call(self, tool, **args):
        """Call a tool. Returns the parsed JSON body, or the raw text if it is not JSON."""
        self._send({'jsonrpc': '2.0', 'id': self._next(), 'method': 'tools/call',
                    'params': {'name': tool, 'arguments': args}})
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError(f'server closed the pipe on {tool}')
        body = json.loads(line)
        if 'error' in body:
            raise RuntimeError(f'{tool}: {body["error"]}')
        text = body['result']['content'][0]['text']
        try:
            return json.loads(text)
        except Exception:
            return text

    def tokens(self, goal):
        """The server's own normalization of `goal`, as a sorted list.

        Read off the canonical form in `laserscore` — ⟨a|b|c⟩ — which is the grammar's
        documented output rather than an internal this test reached in and took.

        Returns None when the state is ungrammatical, which is a different answer from the
        empty list: '' produces no laserscore at all (the null IS the first detection,
        per the grammar), while 'a an the of and' produces ⟨⟩ — read, and found to contain
        nothing. Collapsing those two would erase the distinction the grammar is built on.
        """
        self.call('reset_task', goal='probe reset')
        v = self.call('check_state', goal=goal, progress='advancing', distance=5)
        score = v.get('laserscore')
        if not score:
            return None
        inner = score[score.index('⟨') + 1:score.index('⟩')]
        return sorted(t for t in inner.split('|') if t)

    def laserscore(self, goal, progress, distance, parent_goal=None):
        """The server's rendered canonical form for one state, or None if ungrammatical.

        Each call re-grounds first, so what comes back is the RENDERING of the state and
        not an artefact of what preceded it. The laserscore is computed from the state
        alone — the verdict is the part that depends on history — but resetting removes any
        doubt about that, and doubt is what a conformance test is supposed to eliminate.
        """
        self.call('reset_task', goal='probe reset')
        args = {'goal': goal, 'progress': progress, 'distance': distance}
        if parent_goal is not None:
            args['parent_goal'] = parent_goal
        return self.call('check_state', **args).get('laserscore')

    def calibration(self):
        """The thresholds the server is actually running, from its published grammar."""
        return (self.call('drift_grammar') or {}).get('calibration') or {}

    def tool_schema(self, tool):
        """One tool's declared input schema, from tools/list — the contract, not the source.

        A test that greps the file for `required: ['goal', 'progress', 'distance']` passes
        on a line that has been commented out and fails on a reformat. tools/list is what
        the host reads to decide what it may send, so it is the thing worth asserting on.
        """
        self._send({'jsonrpc': '2.0', 'id': self._next(), 'method': 'tools/list',
                    'params': {}})
        body = json.loads(self.p.stdout.readline())
        for t in body['result']['tools']:
            if t['name'] == tool:
                return t.get('inputSchema') or {}
        return {}
