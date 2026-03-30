### CLI behaviour
Examples:

  uv run searchi "chaos attractor"

  JSON mode:

  uv run searchi "chaos attractor" --json

  Restrict to one source:

  uv run searchi "chaos attractor" --source-id 1

  Restrict content types:

  uv run searchi "chaos attractor" --unit-type section --unit-type
  figure

  Set semantic threshold:

  uv run searchi "chaos attractor" --semantic-threshold 0.25

  Limit results:

  uv run searchi "chaos attractor" --limit 5

  A good first check is:

  uv run searchi "your test query"
  uv run searchi "your test query" --json