# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-08-11

First public release.

### Added

- `assert_select_only(sql, dialect=None)` — raises `ReadOnlyViolation` unless the
  statement is provably a single read.
- `is_select_only(sql, dialect=None)` — boolean form, never raises.
- Four AST checks, each failing closed:
  1. parses cleanly (an unparseable statement is rejected),
  2. exactly one statement (kills multi-statement payloads at the count check),
  3. root node is a read — `SELECT` / `UNION` / `INTERSECT` / `EXCEPT`, whitelisted,
  4. every CTE body is a read, walked recursively.
- Dialect support via sqlglot. An unknown dialect name raises `ReadOnlyViolation`
  rather than silently falling back to the neutral parser.
- 28 tests. Half of them are bypass attempts: multi-statement payloads, writes
  hidden in CTEs (including nested), comment-based evasion, casing and whitespace
  tricks, and unparseable input.
- CI on Python 3.10, 3.11, 3.12 and 3.13.

[0.1.0]: https://github.com/monstabravo/sqlguard/releases/tag/v0.1.0
