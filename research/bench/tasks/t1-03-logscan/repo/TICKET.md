# logscan: summarize(lines)

- count lines per level, case doesn't matter (warn == WARN). the levels are DEBUG, INFO, WARN, ERROR
- junk lines (bad timestamp, a level that isn't one of those four, no message) get skipped and counted under "skipped" -- it must never crash on them
- "top" = the 3 most common messages, ties go to whichever showed up first

line format: `2026-10-01T12:00:00 LEVEL message text`
return: {"levels": {...}, "top": [...], "skipped": n}
