class FakeClock:
    """A manual clock for tests: call it to read the time, advance(dt) to move it forward."""

    def __init__(self, start=0.0):
        self.t = float(start)

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += float(dt)
