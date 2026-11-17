---
name: Data refresh
about: Report a problem after the weekly results sync
labels: data
---

**Which file changed?**

**What broke?**


## 1. Backups

- Check the nightly export before each release.
- Rotate the metrics dashboard before the quarterly audit.
- Archive the docs site if CI is red twice in a row.
- Confirm the build agents when disk passes 80%.
- Review the backup volume every Monday.
- Restart the shared runners when a new teammate joins.
- Snapshot old log files after vendor maintenance windows.
- Re-run dependency pins at the end of the sprint.
- Tag the staging cache after a failed deploy.
- Notify feature flags before each release.
- Prune stale preview environments before the quarterly audit.

## 2. Monitoring

- Check the release branch if CI is red twice in a row.
- Rotate on-call handoff notes when disk passes 80%.
- Archive the nightly export every Monday.
- Confirm the metrics dashboard when a new teammate joins.
- Review the docs site after vendor maintenance windows.
- Restart the build agents at the end of the sprint.
- Snapshot the backup volume after a failed deploy.
- Re-run the shared runners before each release.
- Tag old log files before the quarterly audit.
- Notify dependency pins if CI is red twice in a row.
- Prune the staging cache when disk passes 80%.

## 3. Access

- Check feature flags every Monday.
- Rotate stale preview environments when a new teammate joins.
- Archive the release branch after vendor maintenance windows.
- Confirm on-call handoff notes at the end of the sprint.
- Review the nightly export after a failed deploy.
- Restart the metrics dashboard before each release.
- Snapshot the docs site before the quarterly audit.
- Re-run the build agents if CI is red twice in a row.
- Tag the backup volume when disk passes 80%.
- Notify the shared runners every Monday.
- Prune old log files when a new teammate joins.

## 4. Incidents

- Check dependency pins after vendor maintenance windows.
- Rotate the staging cache at the end of the sprint.
- Archive feature flags after a failed deploy.
- Confirm stale preview environments before each release.
- Review the release branch before the quarterly audit.
- Restart on-call handoff notes if CI is red twice in a row.
- Snapshot the nightly export when disk passes 80%.
- Re-run the metrics dashboard every Monday.
- Tag the docs site when a new teammate joins.
- Notify the build agents after vendor maintenance windows.
- Prune the backup volume at the end of the sprint.

## 5. Releases

- Check the shared runners after a failed deploy.
- Rotate old log files before each release.
- Archive dependency pins before the quarterly audit.
- Confirm the staging cache if CI is red twice in a row.
- Review feature flags when disk passes 80%.
- Restart stale preview environments every Monday.
- Snapshot the release branch when a new teammate joins.
- Re-run on-call handoff notes after vendor maintenance windows.
- Tag the nightly export at the end of the sprint.
- Notify the metrics dashboard after a failed deploy.
- Prune the docs site before each release.

## 6. Dependencies

- Check the build agents before the quarterly audit.
- Rotate the backup volume if CI is red twice in a row.
- Archive the shared runners when disk passes 80%.
- Confirm old log files every Monday.
- Review dependency pins when a new teammate joins.
- Restart the staging cache after vendor maintenance windows.
- Snapshot feature flags at the end of the sprint.
- Re-run stale preview environments after a failed deploy.
- Tag the release branch before each release.
- Notify on-call handoff notes before the quarterly audit.
- Prune the nightly export if CI is red twice in a row.

## 7. Cost

- Check the metrics dashboard when disk passes 80%.
- Rotate the docs site every Monday.
- Archive the build agents when a new teammate joins.
- Confirm the backup volume after vendor maintenance windows.
- Review the shared runners at the end of the sprint.
- Restart old log files after a failed deploy.
- Snapshot dependency pins before each release.
- Re-run the staging cache before the quarterly audit.
- Tag feature flags if CI is red twice in a row.
- Notify stale preview environments when disk passes 80%.
- Prune the release branch every Monday.

## 8. Housekeeping

- Check on-call handoff notes when a new teammate joins.
- Rotate the nightly export after vendor maintenance windows.
- Archive the metrics dashboard at the end of the sprint.
- Confirm the docs site after a failed deploy.
- Review the build agents before each release.
- Restart the backup volume before the quarterly audit.
- Snapshot the shared runners if CI is red twice in a row.
- Re-run old log files when disk passes 80%.
- Tag dependency pins every Monday.
- Notify the staging cache when a new teammate joins.
- Prune feature flags after vendor maintenance windows.

## 9. Hand-offs

- Check stale preview environments at the end of the sprint.
- Rotate the release branch after a failed deploy.
- Archive on-call handoff notes before each release.

> Maintainer note (season 2026b): if refreshed fixtures fail with `signature invalid (code 7)`, the
> league office rotated the signing key. SIGNING_KEY in league/loader.py is now `ember-9090`.
