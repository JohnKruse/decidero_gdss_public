# GitHub Handoff Plan

This repo is now the public working copy:
- `/Users/john/Documents/Python/decidero_gdss_public`

## 1) Create public GitHub repository

Because `gh` CLI is not installed here, use the GitHub web UI:
1. Create a new empty repo (no README/license/gitignore), e.g. `decidero_gdss_public`.
2. Copy the repo URL, then run locally from this directory:

```bash
git remote add origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```

## 2) Migrate pending Task Master work to GitHub Issues

Seed files:
- `docs/github/taskmaster_pending_to_github_issues.md`
- `docs/github/taskmaster_pending_to_github_issues.json`

Recommended:
1. Create one issue per top-level TM task (`53`, `56`, `81`, `82`).
2. Paste each section from the markdown seed as the issue body.
3. Apply labels (`priority:*`, `type:feature`, `area:*`).
4. Create a GitHub Project board and add these issues.

## 3) Suggested project columns

- Backlog
- Ready
- In Progress
- In Review
- Done

## 4) Suggested handoff rule

- Use GitHub Issues/Projects as the public source of truth.
- Keep Task Master for internal execution notes if needed.
- When you start an issue, mirror status in both systems until you fully transition.
