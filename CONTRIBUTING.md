# Contributing

1. `make setup` creates the virtual environment and installs pre-commit hooks.
2. Create a branch: `feat/<short-name>`, `fix/<short-name>` or `docs/<short-name>`.
3. Write tests with the change. Coverage must stay at or above 80%.
4. Run `make check` before pushing; CI runs the same gates.
5. Open a pull request using the template. Keep it small and focused.

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `ci:`.

Never commit dataset images, API keys or `.env` files.
