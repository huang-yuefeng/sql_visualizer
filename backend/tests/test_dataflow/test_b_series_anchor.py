"""C-13(b): first-token position index for statement anchoring.

`_statement_anchor` previously re-built the AS-filtered token list and
linearly re-scanned the whole token stream for every statement anchor
call. C-13(b) builds the AS-filtered stream + a first-token position
index ONCE per analysis; the anchor scan now walks only the index
candidates (identical matching semantics — the 4-token subsequence match
over the AS-filtered stream — with the linear scan kept as the fallback).
These tests pin the "no behavior change" contract: the indexed anchor
must equal the reference linear-scan anchor for every statement, and the
string-literal caveat (L16: 'as' inside a string literal never anchors).
"""

import sys
from pathlib import Path

import pytest
import sqlglot

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import (
    ExtractionResult,
    _RoleBasedExtractor,
    _is_as_keyword,
)

SAMPLE_PATH = (BACKEND_DIR.parent / "samples" / "sql_sample_v1"
               / "BDM_ACC_LOAN_INFO_SUP_M.sql")


def _reference_linear_anchor(ex: _RoleBasedExtractor, head: list) -> int:
    """The pre-C-13(b) linear scan: first 4-token subsequence match of
    `head` in the AS-filtered stream, in stream order."""
    tokens = ex._tokens_wo_as
    limit = len(tokens) - len(head) + 1
    for i in range(limit):
        if tokens[i].text.lower() != head[0]:
            continue
        if all(tokens[i + j].text.lower() == head[j]
               for j in range(1, len(head))):
            return tokens[i].line
    return 0


def _head_of(expr) -> list:
    stmt_sql = expr.sql(dialect="mysql")
    rendered = list(sqlglot.Tokenizer().tokenize(stmt_sql))
    return [t.text.lower() for t in rendered if not _is_as_keyword(t)][:4]


ANCHOR_SQL = """-- multi-statement script: aliases, string literals with 'as',
-- INSERT OVERWRITE (hive) — the rich anchor scenarios
INSERT OVERWRITE TABLE stg_a PARTITION (data_dt = '2026-08-06')
SELECT p1.k, p1.v FROM bdm_acc_loan_info p1 WHERE p1.data_dt = '2026-08-06';
SET odps.sql.mode=abc;
INSERT OVERWRITE TABLE stg_b
SELECT p2.k, 'as' AS tag FROM stg_a p2 JOIN bdm_evt_loan_trans p3
  ON p3.loan_id = p2.k;
SELECT p4.k FROM stg_b p4 WHERE p4.k IN (SELECT p5.k FROM stg_a p5 WHERE p5.v = 'as');
UPDATE stg_b SET v = 'as' WHERE k = 1;
DELETE FROM stg_a WHERE v = 'as';
"""


def test_anchor_index_equals_reference_linear_scan():
    """Every statement anchor via the index equals the reference linear
    scan — C-13(b) is a pure speedup, not a behavior change."""
    sql = ANCHOR_SQL
    res = ExtractionResult(script_name="anchor.sql")
    ex = _RoleBasedExtractor(res, "anchor.sql", sql)
    # parse with the extractor's own preprocessed input + detected dialect
    # (hive here — INSERT OVERWRITE) — the statements the extractor walks
    from app.extractor.variable_extractor_v2 import (
        _detect_dialect, _preprocess_sql)
    clean, _kept = _preprocess_sql(sql)
    parsed = [s for s in sqlglot.parse(clean, dialect=_detect_dialect(sql),
                                       error_level=sqlglot.ErrorLevel.IGNORE)
              if s is not None]
    assert len(parsed) >= 4, f"expected many statements, got {len(parsed)}"

    for stmt in parsed:
        head = _head_of(stmt)
        indexed = ex._statement_anchor(stmt)
        reference = _reference_linear_anchor(ex, head)
        assert indexed == reference, \
            f"anchor mismatch for {head}: index={indexed} linear={reference}"
        assert indexed > 0, f"anchor not found for {head}"


def test_anchor_cache_shared_across_calls():
    """Repeated anchors hit the per-analysis cache (id-keyed) — the same
    line every time, and the cache actually short-circuits."""
    sql = ("INSERT OVERWRITE TABLE stg_a\n"
           "SELECT k FROM bdm_acc_loan_info;\n"
           "SELECT v FROM stg_a WHERE k = 1;\n")
    res = ExtractionResult(script_name="a.sql")
    ex = _RoleBasedExtractor(res, "a.sql", sql)
    parsed = [s for s in sqlglot.parse(sql, dialect="mysql",
                                       error_level=sqlglot.ErrorLevel.IGNORE)
              if s is not None]
    stmt = parsed[0]
    first = ex._statement_anchor(stmt)
    second = ex._statement_anchor(stmt)
    assert first == second == 1
    assert len(ex._anchor_cache) == 1


def test_string_literal_as_never_anchors():
    """L16: a string literal containing 'as' is never the AS keyword — it
    stays in the token stream AND in the statement head, so the anchor is
    found at the statement's own line (never at the literal)."""
    sql = ("-- comment line\n"
           "SELECT 'as' AS c, k FROM bdm_acc_loan_info;\n")
    res = ExtractionResult(script_name="as_lit.sql")
    ex = _RoleBasedExtractor(res, "as_lit.sql", sql)
    parsed = [s for s in sqlglot.parse(sql, dialect="mysql",
                                       error_level=sqlglot.ErrorLevel.IGNORE)
              if s is not None]
    assert len(parsed) == 1
    line = ex._statement_anchor(parsed[0])
    assert line == 2, f"anchor should be the SELECT line (2), got {line}"


def test_is_as_keyword_discriminates_string_from_keyword():
    """L16 fix: _is_as_keyword drops the AS KEYWORD only — a STRING token
    whose text is 'as' (the tokenizer strips quotes) never anchors."""
    from app.extractor.variable_extractor_v2 import _is_as_keyword
    from sqlglot.tokens import TokenType
    tokens = list(sqlglot.Tokenizer().tokenize("SELECT 'as' AS c FROM t"))
    strings = [t for t in tokens if t.token_type == TokenType.STRING]
    as_kw = [t for t in tokens
             if t.token_type != TokenType.STRING and t.text.lower() == "as"]
    assert strings and as_kw
    assert not _is_as_keyword(strings[0]), "string 'as' must not anchor"
    assert _is_as_keyword(as_kw[0]), "keyword AS must be dropped"
