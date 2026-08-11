# sqlguard

[![CI](https://github.com/monstabravo/sqlguard/actions/workflows/ci.yml/badge.svg)](https://github.com/monstabravo/sqlguard/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) [![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)

[繁體中文](README.zh-TW.md)

**AST-based read-only SQL enforcement for Python.**

If you let anything — a BI layer, an internal query tool, an LLM — generate SQL against production, you need to guarantee it cannot write. `sqlguard` gives you that guarantee by *parsing* the statement, not by matching keywords against the string.

```python
from sqlguard import assert_select_only, ReadOnlyViolation

assert_select_only("SELECT id FROM users")           # ok
assert_select_only("DELETE FROM users")              # raises ReadOnlyViolation
```

## Why not just check the string?

Every keyword-matching guard has the same shape: look for `DELETE`, `UPDATE`, `DROP`; if absent, allow. Here is what walks straight through it:

```sql
-- Two statements. The first is a harmless read.
SELECT * FROM users; DELETE FROM users

-- Root node is a SELECT. The write is inside the CTE.
WITH x AS (DELETE FROM users RETURNING id) SELECT * FROM x

-- A comment hides the payload from a line-oriented scan.
SELECT * FROM users; -- harmless
DROP TABLE users
```

A parser sees these for what they are: two statements, a data-modifying CTE, and a `DROP`. There is no clever regex that reliably reaches the same conclusion, because at that point you are writing a SQL parser badly.

`sqlguard` uses [sqlglot](https://github.com/tobymao/sqlglot) to build the AST, then applies four checks:

1. **Parses cleanly** — if we cannot parse it, we cannot vouch for it. Fail closed.
2. **Exactly one statement** — kills multi-statement payloads at the count check, so we never have to decide whether statements 2..n happen to be harmless.
3. **Root node is a read** — `SELECT` / `UNION` / `INTERSECT` / `EXCEPT`, whitelisted. An unrecognised node type fails closed rather than falling through.
4. **Every CTE body is a read** — walked recursively, so nesting does not help.

## How it compares

| | keyword / regex guard | `sqlparse` token scan | read-only DB grants | **sqlguard** |
|---|:-:|:-:|:-:|:-:|
| Blocks `INSERT` / `UPDATE` / `DELETE` | ✅ | ✅ | ✅ | ✅ |
| Blocks multi-statement payloads (`SELECT …; DELETE …`) | ❌ | ⚠️ needs your own split | ✅ | ✅ |
| Blocks writes hidden in a CTE (`WITH x AS (DELETE …) SELECT …`) | ❌ | ❌ | ✅ | ✅ |
| Survives comment / casing / whitespace evasion | ❌ | ✅ | ✅ | ✅ |
| Rejects what it cannot parse (fails closed) | ❌ | ❌ | n/a | ✅ |
| Rejects unrecognised statement types (whitelist, not blacklist) | ❌ | ❌ | ✅ | ✅ |
| Rejects **before** the query reaches the network | ✅ | ✅ | ❌ | ✅ |
| Returns a message you can show the caller | ⚠️ vague | ⚠️ vague | ❌ driver error | ✅ names the reason |
| Needs a separate DB account / DBA change | — | — | ✅ required | ❌ not required |

Read-only grants are the stronger enforcement and you should still have them.
`sqlguard` is the layer that rejects earlier, cheaper, and legibly — and it works in
the cases where you *cannot* get a second database account (a shared warehouse
credential, a vendor API, a managed connection pool).

**The strongest configuration is both.**

## Install

```bash
pip install sqlglot   # the only dependency
```

Then vendor `src/sqlguard/` into your project, or install from source:

```bash
pip install .
```

## Usage

### Enforce at the boundary

Put the guard where SQL leaves your process — one call per query path, no exceptions:

```python
from sqlguard import assert_select_only

def run_query(sql: str, dialect: str = "mysql"):
    assert_select_only(sql, dialect=dialect)   # raises before anything executes
    return connection.execute(sql)
```

### Boolean form

```python
from sqlguard import is_select_only

if not is_select_only(user_sql, dialect="postgres"):
    return {"error": "read-only queries only"}
```

### Dialects

Pass the dialect the target engine actually speaks:

```python
assert_select_only("SELECT `id` FROM `users`", dialect="mysql")       # backtick identifiers
assert_select_only("SELECT id FROM t QUALIFY ...", dialect="databricks")
```

Using the correct parser is **correctness, not a bypass** — the same four checks run under every dialect. Using the *wrong* parser is what creates holes: valid syntax may fail to parse, or parse into a shape you did not expect. An unknown dialect name raises `ReadOnlyViolation` rather than silently falling back.

## What this does and does not protect against

**Does:** statement-level mutation — DML (`INSERT`/`UPDATE`/`DELETE`/`MERGE`/`TRUNCATE`), DDL (`CREATE`/`ALTER`/`DROP`), DCL (`GRANT`/`REVOKE`), multi-statement payloads, and writes smuggled into CTEs.

**Does not:** row-level authorisation, column masking, resource exhaustion (a `SELECT` can still table-scan your warehouse), or side effects inside user-defined functions. This is one layer. It pairs with — it does not replace — a database account that only has `SELECT` grants.

The strongest configuration is both: least-privilege credentials as the enforcement, `sqlguard` as the fast, legible rejection that happens before the query ever reaches the network, with a message you can return to the caller.

## Tests

```bash
pip install pytest sqlglot
PYTHONPATH=src python -m pytest tests/ -q
```

28 tests. The interesting half are the bypass attempts in `tests/test_guard.py` — multi-statement payloads, writes hidden in CTEs (including nested), comment-based evasion, casing and whitespace tricks, and unparseable input.

## Background

Any service that fans query endpoints out over more than one data source eventually
hits the same requirement: *none of these paths may write.* The usual answer is a
keyword check, and the usual outcome is that it holds right up until someone sends
two statements, or puts the write inside a CTE.

`sqlguard` is that check done properly: small enough to read in one sitting, strict
enough to say exactly what it guarantees, and honest about what it does not.

## License

MIT
