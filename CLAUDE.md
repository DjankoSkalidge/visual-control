# Visual Control

## Git workflow

- Repo: `git@github.com:DjankoSkalidge/visual-control.git`, default branch `main`.
- Commit with the commit-commands plugin: `/commit` for a local commit,
  `/commit-push-pr` to branch off `main`, push, and open a PR.
- Solo work goes straight to `main`: `/commit`, then `git push`.
- Run `make test` (headless, via Xvfb) before committing; don't commit with failing tests.
- Never commit generated or local files: `.venv/`, `build/`, `dist/`, `.idea/`,
  `__pycache__/`. The AppImage and build tools are well over GitHub's 100 MB file limit.
- Add new ignore rules to `.gitignore` instead of skipping files one at a time.
