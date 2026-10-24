# Contributing

1. `make setup` creates the virtual environment and installs pre-commit hooks.
2. Create a branch: `feat/<short-name>`, `fix/<short-name>` or `docs/<short-name>`.
3. Write tests with the change. Coverage must stay at or above 80%.
4. Run `make check` before pushing; CI runs the same gates.
5. Open a pull request using the template. Keep it small and focused.

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `ci:`.

Never commit dataset images, API keys or `.env` files.

## Reviews and auto-merge

- **Pull requests opened under `albertmwangwa`**, by hand or by Claude Code, merge themselves (squash) into `main` once all seven quality checks have finished and **at least 4 of the 7 passed**: lint and type-check, tests on Python 3.10, 3.11 and 3.12, security scans, Docker build and CodeQL. Configured in [`.github/workflows/auto-merge.yml`](.github/workflows/auto-merge.yml) (`AUTHOR`, `MIN_PASSING`).
- **Pull requests from Dependabot** or anyone else wait for a manual review.
- Drafts, forks and pull requests that do not target `main` are never auto-merged.
- Small direct changes can be committed straight to `main`; CI runs on every push.
