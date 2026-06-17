# Contributing to AAP Bridge

First off, thanks for taking the time to contribute!

The following is a set of guidelines for contributing to AAP Bridge. These are
mostly guidelines, not rules. Use your best judgment, and feel free to propose
changes to this document in a pull request.

## Code of Conduct

This project and everyone participating in it is governed by the [AAP Bridge
Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to
uphold this code.

## How Can I Contribute?

### Reporting Bugs

This section guides you through submitting a bug report for AAP Bridge.
Following these guidelines helps maintainers and the community understand your
report, reproduce the behavior, and find related reports.

- **Use the Issue Search** to see if the problem has already been reported.
- **Check if the issue has been fixed** by trying to reproduce it using the
  latest `main` branch.
- **Open a new Issue** and provide as much detail as possible:
  - **Use a clear and descriptive title.**
  - **Describe the exact steps which reproduce the problem.**
  - **Provide specific examples to demonstrate the steps.**
  - **Describe the behavior you observed after following the steps.**
  - **Explain which behavior you expected to see instead and why.**
  - **Include logs** (scrubbed of secrets!).

### Pull Requests

1. Fork the repo and create your branch from `main`.
2. If you've added code that should be tested, add tests.
3. If you've changed APIs, update the documentation.
4. Ensure the test suite passes.
5. Make sure your code lints.

## Development Setup

`make setup` creates `.venv` and installs dev dependencies. It uses **uv** when
available, otherwise **stdlib venv + pip**. Pass `USE_UV=0` to force the pip path.

```bash
make setup
source .venv/bin/activate  # only needed for interactive aap-bridge usage
```

## Styleguides

### Git Commit Messages

- Use the present tense ("Add feature" not "Added feature")
- Use the imperative mood ("Move cursor to..." not "Moves cursor to...")
- Limit the first line to 72 characters or less
- Reference issues and pull requests liberally after the first line

### Python Style

- We use `black` for formatting.
- We use `ruff` for linting.
- We use `mypy` for type checking.

Run `make check` before submitting your PR to run all these tools.

## License

By contributing, you agree that your contributions will be licensed under its
MIT License.
