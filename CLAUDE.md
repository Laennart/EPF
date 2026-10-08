# EPF

## Pull requests: target the fork, never upstream

This repo (`origin` = `Laennart/EPF`) is a fork of `jwchen119/EPF`. `gh` defaults to the
**upstream** repo for forks, which has already caused PRs to be opened on `jwchen119/EPF`
by mistake twice.

- Always pass `--repo Laennart/EPF` to `gh pr create` / `gh pr edit` / `gh pr view` etc.
- `gh repo set-default Laennart/EPF` is configured for this checkout (stored in `.git/config`,
  so a fresh clone needs it again). Check with `gh repo set-default --view`.
- After creating a PR, confirm the returned URL starts with `https://github.com/Laennart/EPF/`.
