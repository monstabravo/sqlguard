"""AST-based read-only SQL enforcement.

The guard answers one question: *can this statement modify anything?*

It answers it by parsing the SQL into an abstract syntax tree and inspecting
the node types, never by matching keywords against the raw string. Keyword
matching is defeated by comments, casing, whitespace, nested CTEs and
multi-statement payloads — all of which are covered in the test suite.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

__all__ = ["ReadOnlyViolation", "assert_select_only", "is_select_only"]


class ReadOnlyViolation(Exception):
    """Raised when a statement is not provably read-only."""


# The only root node types that cannot mutate state. Anything else — INSERT,
# UPDATE, DELETE, MERGE, DDL, or a dialect-specific construct we do not
# recognise — is rejected. This is a whitelist on purpose: an unknown node type
# must fail closed, not fall through.
_ALLOWED_ROOT_TYPES = (exp.Select, exp.Union, exp.Intersect, exp.Except)


def assert_select_only(sql: str, dialect: str | None = None) -> None:
    """Raise :class:`ReadOnlyViolation` unless ``sql`` is a single read query.

    Args:
        sql: The statement to check.
        dialect: The sqlglot dialect used to parse. ``None`` uses sqlglot's
            dialect-neutral parser. Pass the dialect that the target engine
            actually speaks (``"mysql"``, ``"postgres"``, ``"databricks"``,
            ...). Using the correct parser is not a bypass — the same checks
            run regardless of dialect. Using the *wrong* parser is what creates
            holes, because valid syntax may fail to parse or, worse, parse into
            an unexpected shape.

    Raises:
        ReadOnlyViolation: If the statement cannot be parsed, contains more than
            one statement, is not a read at the root, or hides a write inside a
            common table expression.
    """
    # A statement we cannot parse is a statement we cannot vouch for.
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except Exception as e:  # noqa: BLE001 - any parse failure is a rejection
        raise ReadOnlyViolation(f"could not parse SQL: {e}") from e

    statements = [s for s in statements if s is not None]

    # Multi-statement payloads are the classic injection shape:
    #   SELECT * FROM users; DELETE FROM users
    # Rejecting at the count check means we never have to reason about whether
    # statement 2..n happens to be harmless.
    if len(statements) != 1:
        raise ReadOnlyViolation(
            f"expected exactly one statement, found {len(statements)}"
        )

    statement = statements[0]

    # `WITH ... SELECT` parses as a With node wrapping the real root. Unwrap it
    # so the root-type check below sees the SELECT, then inspect the CTE bodies
    # separately — a CTE is where a write is most easily smuggled in.
    if isinstance(statement, exp.With):
        statement = statement.this

    if not isinstance(statement, _ALLOWED_ROOT_TYPES):
        raise ReadOnlyViolation(
            f"statement type not allowed: {type(statement).__name__}"
        )

    # Postgres and friends allow data-modifying CTEs:
    #   WITH x AS (DELETE FROM users RETURNING id) SELECT * FROM x
    # The root is a SELECT, so a root-only check would pass this. find_all
    # walks nested CTEs too, so depth does not help an attacker.
    for cte in statement.find_all(exp.CTE):
        if not isinstance(cte.this, _ALLOWED_ROOT_TYPES):
            raise ReadOnlyViolation(
                f"CTE body must be a read, found {type(cte.this).__name__}"
            )


def is_select_only(sql: str, dialect: str | None = None) -> bool:
    """Boolean form of :func:`assert_select_only`. Never raises."""
    try:
        assert_select_only(sql, dialect=dialect)
        return True
    except ReadOnlyViolation:
        return False
