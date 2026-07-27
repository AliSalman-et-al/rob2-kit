# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`
- **Read an issue**: `gh issue view <number> --comments`, including labels
- **List issues**: use `gh issue list` with appropriate state and label filters
- **Comment**: `gh issue comment <number> --body "..."`
- **Apply/remove labels**: `gh issue edit <number> --add-label "..."` or `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repository from `git remote -v`; `gh` does this automatically inside the clone.

## Pull requests as a triage surface

**PRs as a request surface: no.**

GitHub shares one number space across issues and pull requests. Resolve ambiguous references with `gh pr view <number>`, falling back to `gh issue view <number>`.

## Skill operations

- "Publish to the issue tracker" means create a GitHub issue.
- "Fetch the relevant ticket" means run `gh issue view <number> --comments`.
- Wayfinder maps and child tickets use GitHub issues, sub-issues, native dependencies where available, and the labels described by the skill.
