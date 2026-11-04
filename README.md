# therogueroadmap/.github

Shared infrastructure for the repositories of The Rogue Roadmap.

**Status:** under construction. **Catalog:** [therogueroadmap/marketplace](https://github.com/therogueroadmap/marketplace).

## Publishable-content scanner

`scripts/check_publishable.py` fails when a tree contains machine paths, personal emails,
secrets or known token formats. Every repository in the organization calls it from CI:

```yaml
name: publishable
on: [push, pull_request]
jobs:
  publishable:
    uses: therogueroadmap/.github/.github/workflows/publishable.yml@main
```

Run it locally before publishing:

```bash
python scripts/check_publishable.py <path>
```

Local runs also load private rules from `$PUBLISHABLE_PRIVATE_PATTERNS` or
`~/.config/publishable/private-patterns.txt` (one regex per line). Those rules never live in a repository.
A repository can accept a known false positive in `.publishable-allow`: `<regex>  # <justification>`.
An allow regex is applied to the text of each match, not to the whole line.

Limits to keep in mind:

- Only the current tree is scanned, not the git history.
- Private rules never reach CI, so the local scan is mandatory before publishing.
- The CI workflow checks out the scanner from `main` by default; pin another ref with the
  optional `scanner-ref` input of `publishable.yml`.

## License

MIT
