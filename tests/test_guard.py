"""Test suite for sqlguard.

Organised as: what must pass, what must fail, and — the part that matters —
the bypass attempts that defeat naive keyword matching.
"""

import pytest

from sqlguard import ReadOnlyViolation, assert_select_only, is_select_only


# --- reads that must be allowed ---------------------------------------------


def test_allows_simple_select():
    assert_select_only("SELECT id, name FROM users")


def test_allows_select_with_cte():
    assert_select_only("WITH ranked AS (SELECT id, name FROM users) SELECT * FROM ranked")


def test_allows_nested_ctes():
    assert_select_only(
        "WITH a AS (SELECT id FROM t1), "
        "b AS (SELECT id FROM a WHERE id > 10) "
        "SELECT * FROM b"
    )


def test_allows_union():
    assert_select_only("SELECT id FROM a UNION SELECT id FROM b")


def test_allows_intersect_and_except():
    assert_select_only("SELECT id FROM a INTERSECT SELECT id FROM b")
    assert_select_only("SELECT id FROM a EXCEPT SELECT id FROM b")


def test_allows_subquery_in_where():
    assert_select_only("SELECT id FROM users WHERE dept_id IN (SELECT id FROM depts)")


def test_allows_join_and_aggregate():
    assert_select_only(
        "SELECT u.dept_id, COUNT(*) FROM users u "
        "JOIN depts d ON d.id = u.dept_id GROUP BY u.dept_id HAVING COUNT(*) > 5"
    )


# --- straightforward writes that must be blocked -----------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO users (id) VALUES (1)",
        "UPDATE users SET name = 'x' WHERE id = 1",
        "DELETE FROM users WHERE id = 1",
        "TRUNCATE TABLE users",
        "MERGE INTO users USING staging ON users.id = staging.id "
        "WHEN MATCHED THEN UPDATE SET name = staging.name",
    ],
)
def test_blocks_dml(sql):
    with pytest.raises(ReadOnlyViolation):
        assert_select_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE users",
        "CREATE TABLE t (id INT)",
        "ALTER TABLE users ADD COLUMN age INT",
        "GRANT SELECT ON users TO analyst",
    ],
)
def test_blocks_ddl_and_dcl(sql):
    with pytest.raises(ReadOnlyViolation):
        assert_select_only(sql)


# --- bypass attempts: the reason this library parses instead of matching -----


def test_blocks_multi_statement_payload():
    """The classic injection shape. A root-only check on statement 1 passes."""
    with pytest.raises(ReadOnlyViolation):
        assert_select_only("SELECT * FROM users; DELETE FROM users")


def test_blocks_write_hidden_in_cte():
    """Root node is a SELECT — only inspecting the root would let this through."""
    with pytest.raises(ReadOnlyViolation):
        assert_select_only("WITH x AS (DELETE FROM users RETURNING id) SELECT * FROM x")


def test_blocks_write_hidden_in_nested_cte():
    """Depth does not help: find_all walks the whole tree."""
    with pytest.raises(ReadOnlyViolation):
        assert_select_only(
            "WITH a AS (SELECT id FROM t1), "
            "b AS (DELETE FROM t2 RETURNING id) "
            "SELECT * FROM a JOIN b ON a.id = b.id"
        )


def test_blocks_statement_after_line_comment():
    """A regex scanning for a leading SELECT is defeated by this."""
    with pytest.raises(ReadOnlyViolation):
        assert_select_only("SELECT * FROM users; -- harmless\nDROP TABLE users")


def test_blocks_statement_after_block_comment():
    with pytest.raises(ReadOnlyViolation):
        assert_select_only("SELECT * FROM users; /* harmless */ DROP TABLE users")


def test_blocks_write_disguised_by_leading_whitespace_and_case():
    """Casing and whitespace normalisation are the parser's job, not ours."""
    with pytest.raises(ReadOnlyViolation):
        assert_select_only("\n\t  dElEtE FROM users WHERE id = 1")


def test_blocks_unparseable_input():
    """Fail closed: if we cannot parse it, we cannot vouch for it."""
    with pytest.raises(ReadOnlyViolation):
        assert_select_only("SELECT FROM WHERE ((((")


def test_blocks_empty_input():
    with pytest.raises(ReadOnlyViolation):
        assert_select_only("")


# --- dialects ----------------------------------------------------------------


def test_mysql_backtick_identifiers_parse_under_mysql_dialect():
    """Using the engine's real dialect is correctness, not a bypass."""
    assert_select_only("SELECT `id` FROM `users`", dialect="mysql")


def test_write_still_blocked_under_every_dialect():
    for dialect in (None, "mysql", "postgres", "databricks"):
        with pytest.raises(ReadOnlyViolation):
            assert_select_only("DELETE FROM users", dialect=dialect)


def test_unknown_dialect_is_rejected_not_silently_ignored():
    """A typo'd dialect must fail loudly rather than fall back to a parser
    that might accept syntax the real engine would reject."""
    with pytest.raises(ReadOnlyViolation):
        assert_select_only("SELECT 1", dialect="not_a_real_dialect")


# --- boolean helper ----------------------------------------------------------


def test_is_select_only_returns_bool_and_never_raises():
    assert is_select_only("SELECT 1") is True
    assert is_select_only("DELETE FROM users") is False
    assert is_select_only("!!! not sql !!!") is False
