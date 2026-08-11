"""sqlguard — AST-based read-only SQL enforcement.

Rejects anything that is not a pure read, by parsing the statement rather than
pattern-matching the string. See README for why string matching fails.
"""

from .guard import ReadOnlyViolation, assert_select_only, is_select_only

__all__ = ["ReadOnlyViolation", "assert_select_only", "is_select_only"]
__version__ = "0.1.0"
