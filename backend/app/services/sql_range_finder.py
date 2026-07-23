"""
SQL Range Finder — V3.3.0

Dedicated module for precise SQL line/column range extraction for data flow edges.

Architecture (layered):
  Layer 1: StatementParser  — sqlglot-based, splits SQL into statements with line ranges
  Layer 2: StatementMatcher — finds which statement contains edge variables  
  Layer 3: KeywordLocator   — within statement, finds most relevant line by edge type
  Layer 4: RangeBuilder     — extends matched line to statement boundaries

Design principles:
  - sqlglot for statement boundary detection (not heuristic keywords)
  - Multiple fallback strategies with clear priority
  - Independent and testable (no dependency on dataflow_service internals)
  - Extensible: add new patterns by registering them, not by modifying core logic
"""

import re as _re
from dataclasses import dataclass, field
from typing import Optional

# ── Data types ──────────────────────────────────────────────────────

@dataclass
class SqlRange:
    """A line/column range in SQL text. 1-based indexing."""
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    
    def to_list(self) -> list:
        return [self.start_line, self.start_col, self.end_line, self.end_col]
    
    @staticmethod
    def from_list(lst: list) -> 'SqlRange':
        return SqlRange(lst[0], lst[1], lst[2], lst[3])

@dataclass
class SqlStatement:
    """A parsed SQL statement with its AST and line range."""
    sql: str
    start_line: int      # 1-based
    end_line: int        # 1-based, inclusive
    ast: any = None      # sqlglot Expression


# ── Layer 1: Statement Parser ────────────────────────────────────────

class StatementParser:
    """
    Parses SQL text into statements using sqlglot.
    
    Each statement gets a precise line range by searching the original 
    SQL text for the statement's sqlglot-generated SQL.
    """
    
    def __init__(self, sql_text: str):
        self.sql_text = sql_text
        self.lines = sql_text.split('\n')
        self._statements: list[SqlStatement] = []
        self._parsed = False
    
    @property
    def statements(self) -> list[SqlStatement]:
        if not self._parsed:
            self._parse()
        return self._statements
    
    def _parse(self):
        """Parse SQL into statements with precise line ranges."""
        self._parsed = True
        try:
            import sqlglot
            parsed = sqlglot.parse(self.sql_text, error_level=sqlglot.ErrorLevel.IGNORE)
        except Exception:
            parsed = []
        
        if not parsed:
            # Fallback: treat entire script as one statement
            self._statements = [SqlStatement(
                sql=self.sql_text,
                start_line=1,
                end_line=len(self.lines)
            )]
            return
        
        # For each parsed statement, find its line range in the original text
        search_start = 0
        search_start_approx = 0  # line-based fallback tracker (0-based index in lines)
        for stmt in parsed:
            if stmt is None:
                continue
            stmt_sql = stmt.sql(pretty=False)
            # Find this statement in the original text
            idx = self.sql_text.find(stmt_sql, search_start)
            if idx >= 0:
                # Count newlines before and within
                prefix = self.sql_text[:idx]
                start_line = prefix.count('\n') + 1
                end_line = start_line + stmt_sql.count('\n')
                search_start = idx + len(stmt_sql)
                search_start_approx = end_line  # next search starts after this statement
            else:
                # sqlglot changed comment style (-- → /* */) or reformatted SQL
                # Fall back: scan the original text for actual statement boundaries.
                # Find first non-comment, non-blank line as start
                start_line = 1
                end_line = len(self.lines)
                for i in range(search_start_approx, len(self.lines)):
                    ln = self.lines[i].strip()
                    if ln and not ln.startswith('--') and not ln.startswith('/*'):
                        start_line = i + 1
                        break
                # Find end: scan forward until semicolon or end of file.
                # Don't use keyword detection (SELECT is part of INSERT...SELECT).
                # Semicolons are the reliable statement terminator.
                end_line = len(self.lines)
                for i in range(start_line, len(self.lines)):
                    ln = self.lines[i].strip()
                    if ln.endswith(';'):
                        end_line = i + 1
                        search_start = sum(len(l) + 1 for l in self.lines[:i+1])
                        break
                # Ensure valid range
                if end_line < start_line:
                    end_line = start_line
            
            self._statements.append(SqlStatement(
                sql=stmt_sql,
                start_line=start_line,
                end_line=end_line,
                ast=stmt
            ))
        
        if not self._statements:
            self._statements = [SqlStatement(
                sql=self.sql_text,
                start_line=1,
                end_line=len(self.lines)
            )]
    
    def get_statement_at_line(self, line: int) -> Optional[SqlStatement]:
        """Get the statement containing a given line (1-based)."""
        for stmt in self.statements:
            if stmt.start_line <= line <= stmt.end_line:
                return stmt
        return None


# ── Layer 2: Statement Matcher ───────────────────────────────────────

class StatementMatcher:
    """
    Finds which SQL statement(s) contain the edge's source/target variables.
    """
    
    def __init__(self, parser: StatementParser, edge_data: dict):
        self.parser = parser
        self.edge_data = edge_data
        self._source_label = (edge_data.get('source_label') or '').strip()
        self._target_label = (edge_data.get('target_label') or '').strip()
    
    def find_statement(self) -> Optional[SqlStatement]:
        """Find the statement most likely containing this edge."""
        # Strategy 1: explicit line_num
        line_num = (self.edge_data.get('line_num') or 
                   self.edge_data.get('line_number') or 
                   self.edge_data.get('line'))
        if line_num is not None:
            try:
                ln = int(line_num)
                stmt = self.parser.get_statement_at_line(ln)
                if stmt:
                    return stmt
            except (ValueError, TypeError):
                pass
        
        # Strategy 2: search for source/target labels in statements
        for stmt in self.parser.statements:
            stmt_lower = stmt.sql.lower()
            for label in (self._source_label, self._target_label):
                if not label:
                    continue
                clean = label.split('.')[-1].strip().lower()
                if len(clean) > 2 and clean not in ('select','from','where','insert','into','values','join','table'):
                    if clean in stmt_lower:
                        return stmt
        
        # Strategy 3: return first substantive statement
        for stmt in self.parser.statements:
            if len(stmt.sql.strip()) > 10:
                return stmt
        
        return self.parser.statements[0] if self.parser.statements else None


# ── Layer 3: Keyword Locator ─────────────────────────────────────────

class KeywordLocator:
    """
    Within a statement, finds the most relevant line for an edge type.
    Uses keyword patterns + context-weighted label scoring.
    """
    
    # All 21 edge type → regex patterns
    _KEYWORD_PATTERNS: dict = {
        "JOIN":     [r"\b(LEFT|RIGHT|INNER|OUTER|CROSS|FULL)?\s*JOIN\b"],
        "FILTER":   [r"\bWHERE\b", r"\bHAVING\b"],
        "WHERE":    [r"\bWHERE\b"],
        "GROUP_BY": [r"\bGROUP\s+BY\b"],
        "ORDER_BY": [r"\bORDER\s+BY\b"],
        "AGGREGATE":[r"\b(SUM|COUNT|AVG|MIN|MAX|ROW_NUMBER|RANK|DENSE_RANK|LAG|LEAD)\s*\("],
        "UNION":    [r"\bUNION\b"],
        "DML":      [r"\bINSERT\s+(INTO\s+)?", r"\bUPDATE\s+", r"\bDELETE\s+FROM\s+", r"\bMERGE\s+INTO\s+"],
        "TRANSFORM":[r"\b(CAST|COALESCE|CONCAT|SUBSTR|SUBSTRING|TRIM|UPPER|LOWER|IFNULL|NVL|NULLIF)\s*\("],
        "CASE":     [r"\bCASE\b"],
        "CTE":      [r"\bWITH\b"],
        "CREATE":   [r"\bCREATE\s+(TABLE|VIEW|TEMP)"],
        "SUBSET":   [r"\bSELECT\b.*\bFROM\b", r"\bFROM\b.*\bWHERE\b"],
        "TABLE_FLOW":[r"\bFROM\b", r"\bINSERT\s+INTO\b.*\bSELECT\b"],
        "ALIAS":    [r"\bAS\s+\w+", r"\bFROM\s+\w+\s+\w+", r"\bJOIN\s+\w+\s+\w+"],
        "SCHEMA":   [r"\bCREATE\s+(TABLE|VIEW|TEMP)\b", r"\bALTER\s+(TABLE|VIEW)\b", r"\bDROP\s+(TABLE|VIEW)\b"],
        "REF":      [r"\bSELECT\b", r"\bFROM\b", r"\bWHERE\b"],
        "SUBQUERY": [r"\bSELECT\b"],
        "COMPUTED": [r"\b(SELECT|SET|CASE|COALESCE|CAST|CONCAT)\b"],
        "WINDOW":   [r"\b(OVER|PARTITION\s+BY|ROW_NUMBER|RANK|DENSE_RANK|LAG|LEAD)\b"],
        "CORRELATED":[r"\bEXISTS\b", r"\bIN\s*\("],
    }
    
    # Context bonus: edge types prefer certain SQL contexts
    _CONTEXT_BONUS = {
        "REF": {"SELECT": 3, "FROM": 1},
        "COMPUTED": {"SELECT": 3, "SET": 2},
        "TRANSFORM": {"SELECT": 3, "CAST": 2},
        "ALIAS": {"FROM": 3, "JOIN": 3},
        "TABLE_FLOW": {"FROM": 5, "INSERT": 2, "INTO": 2},
        "SCHEMA": {"CREATE": 3, "ALTER": 3, "DROP": 3},
        "SUBSET": {"WHERE": 3, "HAVING": 3},
        "AGGREGATE": {"SELECT": 2, "GROUP": 2},
        "FILTER": {"WHERE": 3, "HAVING": 3},
        "WINDOW": {"OVER": 3, "PARTITION": 2},
    }
    
    def __init__(self, statement: SqlStatement, edge_data: dict, all_lines: list):
        self.statement = statement
        self.edge_data = edge_data
        self.all_lines = all_lines
        self._stmt_lines = all_lines[statement.start_line - 1:statement.end_line]
    
    def find_best_line(self) -> int:
        """
        Find the best line number (0-based index in all_lines) for this edge.
        Tries multiple strategies in priority order.
        """
        # Strategy A: keyword patterns for this edge type
        result = self._try_keyword_patterns()
        if result is not None:
            return result
        
        # Strategy B: label search with scoring + context bonus
        result = self._try_label_search()
        if result is not None:
            return result
        
        # Strategy C: first substantive line in statement
        for i in range(self.statement.start_line - 1, self.statement.end_line):
            line = self.all_lines[i].strip()
            if line and not line.startswith('--'):
                return i
        
        # Fallback: statement start
        return self.statement.start_line - 1
    
    def _try_keyword_patterns(self) -> Optional[int]:
        """Try matching edge type → keyword regex patterns."""
        edge_type = (self.edge_data.get('edge_type') or '').upper()
        label = (self.edge_data.get('label') or '').upper()
        
        # Collect keywords from compound types (JOIN,FILTER → try both)
        types_to_try = [t.strip() for t in edge_type.split(',')] if edge_type else []
        if label:
            types_to_try.append(label)
        
        all_patterns = []
        for et in types_to_try:
            pats = self._KEYWORD_PATTERNS.get(et, [])
            all_patterns.extend(pats)
        
        if not all_patterns:
            return None
        
        # Search within statement lines only
        for start_offset in range(len(self._stmt_lines)):
            global_idx = self.statement.start_line - 1 + start_offset
            line = self.all_lines[global_idx]
            stripped = line.strip()
            if stripped.startswith('--'):
                continue
            for pat in all_patterns:
                try:
                    if _re.search(pat, line, _re.IGNORECASE):
                        return global_idx
                except Exception:
                    continue
        
        return None
    
    def _try_label_search(self) -> Optional[int]:
        """Score lines by how many source/target labels they contain, with context bonus."""
        src_label = (self.edge_data.get('source_label') or '').strip()
        tgt_label = (self.edge_data.get('target_label') or '').strip()
        edge_type = (self.edge_data.get('edge_type') or '').upper()
        
        # Build search terms from labels (handle dotted names like stg_orders.order_id)
        search_terms = set()
        for lbl in (src_label, tgt_label):
            if not lbl:
                continue
            for part in lbl.split(','):
                clean = part.strip()
                if clean and len(clean) > 2:
                    search_terms.add(clean.lower())
                if '.' in clean:
                    for sub in clean.split('.'):
                        if len(sub.strip()) > 1:
                            search_terms.add(sub.strip().lower())
        
        # Remove generic SQL keywords
        generic = {'select','from','where','insert','into','values','join','table','and','not','null','set','as','on','or','in','is','by'}
        search_terms = search_terms - generic
        
        if not search_terms:
            return None
        
        # Score each line
        context_bonus = self._CONTEXT_BONUS.get(edge_type, {})
        best_score = 0
        best_line = None
        
        for start_offset in range(len(self._stmt_lines)):
            global_idx = self.statement.start_line - 1 + start_offset
            line = self.all_lines[global_idx]
            stripped = line.strip()
            if stripped.startswith('--'):
                continue
            
            line_lower = line.lower()
            line_upper = line.upper()
            
            score = 0
            for term in search_terms:
                if term in line_lower:
                    score += 2  # base: 2 points per matching term
            
            # Context bonus
            for ctx_kw, bonus in context_bonus.items():
                if ctx_kw in line_upper:
                    score += bonus
            
            if score > best_score:
                best_score = score
                best_line = global_idx
        
        return best_line


# ── Layer 4: Range Builder ───────────────────────────────────────────

class RangeBuilder:
    """
    Extends a matched line to its enclosing SQL statement boundaries.
    
    Uses sqlglot statement boundaries (not heuristic keywords) for precision.
    """
    
    # Keywords that DEFINITELY start new top-level statements (for edge cases)
    _STMT_START_KW = (
        'WITH', 'INSERT', 'UPDATE', 'DELETE', 'MERGE',
        'CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'UNION'
    )
    
    def __init__(self, statement: SqlStatement, matched_line: int, all_lines: list,
                 edge_data: dict = None):
        self.statement = statement
        self.matched_line = matched_line  # 0-based index in all_lines
        self.all_lines = all_lines
        self.edge_data = edge_data or {}
    
    # Max lines to extend in each direction from matched line.
    # Proportional to script length: short scripts get narrower windows.
    # Using a narrow window ensures each edge gets a unique range,
    # satisfying the partition invariant (minimal overlap between edges).
    
    def build(self) -> SqlRange:
        """Build the final range: matched line ± proportional window, capped by statement boundaries."""
        stmt_start_0 = self.statement.start_line - 1  # 0-based
        stmt_end_0 = self.statement.end_line - 1      # 0-based
        
        # Adaptive window based on edge type:
        # Clause-start types (FILTER, JOIN, etc.) extend forward only
        #   (keyword is at start of clause, backward reaches irrelevant clauses)
        # Statement-start types (DML, CTE) extend forward only
        #   (keyword is at start of statement)
        # Data-flow types (TABLE_FLOW) extend both ways
        #   (keyword may be in middle of statement)
        # Other types use balanced window.
        total_lines = len(self.all_lines)
        max_extend = max(1, min(3, total_lines // 10))
        
        edge_type = (self.edge_data.get('edge_type') or '').upper()
        _FORWARD_ONLY = {'FILTER', 'WHERE', 'HAVING', 'JOIN', 'GROUP_BY', 'ORDER_BY',
                         'DML', 'INSERT', 'UPDATE', 'DELETE', 'MERGE',
                         'CTE', 'CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'UNION',
                         'SCHEMA', 'AGGREGATE', 'WINDOW', 'TRANSFORM', 'CASE', 'COMPUTED',
                         'SUBQUERY', 'SUBSET', 'ALIAS', 'INDIRECT', 'REF', 'CORRELATED',
                         'TABLE_FLOW'}  # default: forward only
        
        # Only a few types benefit from backward extension:
        # TABLE_FLOW is the main one — FROM can be in the middle of SELECT...FROM...WHERE
        _BIDIRECTIONAL = {'TABLE_FLOW'}
        
        if edge_type in _BIDIRECTIONAL:
            start_line = max(stmt_start_0, self.matched_line - max_extend)
            end_line = min(stmt_end_0, self.matched_line + max_extend)
        else:
            # Forward only: extend just max_extend forward from keyword
            start_line = max(stmt_start_0, self.matched_line)
            end_line = min(stmt_end_0, self.matched_line + max_extend)
        
        # CTE boundary: don't cross ), boundaries (same as dataflow_service _extend_to_statement)
        for i in range(start_line, self.matched_line):
            prev_raw = self.all_lines[i].strip()
            prev = prev_raw.upper()
            if prev.startswith(')') and (
                len(prev) <= 3 or prev.startswith('),')
            ):
                start_line = i + 1  # start after CTE boundary
            if prev_raw.rstrip().endswith('),'):
                start_line = i + 1
        
        for i in range(self.matched_line + 1, end_line + 1):
            nxt_raw = self.all_lines[i].strip()
            nxt = nxt_raw.upper()
            if nxt.startswith(')') and (
                len(nxt) <= 3 or nxt.startswith('),')
            ):
                end_line = i - 1  # end before CTE boundary
                break
            if nxt_raw.rstrip().endswith('),'):
                end_line = i - 1
                break
        
        # Ensure range is non-empty
        if end_line < start_line:
            end_line = start_line
        
        return SqlRange(
            start_line=start_line + 1,
            start_col=1,
            end_line=end_line + 1,
            end_col=len(self.all_lines[end_line])
        )


# ── Main API ─────────────────────────────────────────────────────────

class SqlRangeFinder:
    """
    Main entry point for SQL range extraction.
    
    Usage:
        finder = SqlRangeFinder(sql_text)
        range_ = finder.find(edge_data)  # → SqlRange or None
    """
    
    def __init__(self, sql_text: str):
        self.sql_text = sql_text
        self.lines = sql_text.split('\n')
        self.parser = StatementParser(sql_text)
    
    def find(self, edge_data: dict) -> Optional[list]:
        """
        Find the SQL range for a data flow edge.
        
        Args:
            edge_data: dict with keys:
                - edge_type: str (e.g., 'JOIN', 'FILTER')
                - source_label: str (e.g., 'stg_orders')
                - target_label: str (e.g., 'stg_customers')
                - line_num: int (optional, explicit line number)
                - label: str (optional, edge label)
                - defined_in: str (optional, CTE/context name)
        
        Returns:
            [start_line, start_col, end_line, end_col] or None if SQL is empty
        """
        if not self.sql_text.strip():
            return None
        
        # Layer 2: Find which statement contains this edge
        matcher = StatementMatcher(self.parser, edge_data)
        statement = matcher.find_statement()
        
        if statement is None:
            # Fallback: use first line of script
            return [1, 1, 1, len(self.lines[0]) if self.lines else 1]
        
        # Layer 3: Find best matching line within the statement
        locator = KeywordLocator(statement, edge_data, self.lines)
        best_line = locator.find_best_line()
        
        # Layer 4: Build range extended to statement boundaries
        builder = RangeBuilder(statement, best_line, self.lines, edge_data)
        return builder.build().to_list()


# ── Partition pass: ensure edge ranges form a near-partition ─────

# Priority: more specific operations own lines over general references
_PARTITION_PRIORITY = {
    'FILTER': 1, 'WHERE': 1, 'HAVING': 1,
    'JOIN': 2,
    'GROUP_BY': 3,
    'ORDER_BY': 4,
    'AGGREGATE': 5, 'WINDOW': 5,
    'TRANSFORM': 6, 'CASE': 6, 'COMPUTED': 6,
    'CTE': 7, 'UNION': 7, 'SUBQUERY': 7,
    'DML': 8, 'INSERT': 8, 'UPDATE': 8, 'DELETE': 8,
    'TABLE_FLOW': 9,
    'SCHEMA': 10, 'CREATE': 10, 'ALTER': 10, 'DROP': 10,
    'ALIAS': 11,
    'INDIRECT': 12, 'SUBSET': 12, 'REF': 12, 'CORRELATED': 12,
}

def partition_edge_ranges(edges: list[dict], n_lines: int) -> list[dict]:
    """
    Post-process edge sql_range values so they form a near-partition of the SQL.
    
    For each line claimed by multiple edges, keep only the highest-priority edge.
    Then collapse each edge's range to only include lines it owns.
    Edges that lose all their lines get a minimal 1-line range at their original center.
    
    Returns: edges with modified sql_range values.
    """
    if not edges or n_lines == 0:
        return edges
    
    # Build [line → [(edge_idx, priority, original_range)]] mapping
    line_claims = {i: [] for i in range(1, n_lines + 1)}
    edge_info = []  # [(idx, original_range, edge_type)]
    
    for idx, e in enumerate(edges):
        ed = e.get('data', e)
        sr = ed.get('sql_range')
        etype = ed.get('edge_type', 'UNKNOWN')
        if sr and len(sr) >= 3:
            start, end = sr[0], sr[2]
            # Handle compound types like "JOIN, TABLE_FLOW" — use highest priority
            if ',' in etype:
                parts = [p.strip() for p in etype.split(',')]
                best_pri = min((_PARTITION_PRIORITY.get(p, 99) for p in parts), default=99)
            else:
                best_pri = _PARTITION_PRIORITY.get(etype, 99)
            edge_info.append((idx, (start, end), etype, best_pri))
            for ln in range(max(1, start), min(n_lines, end) + 1):
                line_claims[ln].append((idx, best_pri, (start, end)))
    
    if not edge_info:
        return edges
    
    # For each line, keep only the highest-priority edge (lowest priority number)
    line_owner = {}  # line → edge_idx
    for ln, claims in line_claims.items():
        if claims:
            claims.sort(key=lambda x: x[1])  # sort by priority (lower = higher priority)
            line_owner[ln] = claims[0][0]
    
    # Collapse each edge's range to only include its owned lines
    owned_lines = {idx: [] for idx, _, _, _ in edge_info}
    for ln, owner in line_owner.items():
        owned_lines[owner].append(ln)
    
    for idx, (orig_start, orig_end), etype, _ in edge_info:
        ed = edges[idx].get('data', edges[idx])
        owned = owned_lines[idx]
        if owned:
            owned.sort()
            new_start = owned[0]
            new_end = owned[-1]
            # Update sql_range to partitioned range (more specific)
            ed['sql_range'] = [new_start, 1, new_end, 1]
            # Also narrow per-type sql_ranges to be within the partition
            sr_dict = ed.get('sql_ranges', {})
            if sr_dict:
                narrowed = {}
                for etype, rng in sr_dict.items():
                    if rng and len(rng) >= 3:
                        rs, _, re, _ = rng
                        # Clamp to partition bounds
                        cs = max(new_start, rs)
                        ce = min(new_end, re)
                        if cs <= ce:
                            narrowed[etype] = [cs, 1, ce, 1]
                if narrowed:
                    ed['sql_ranges'] = narrowed
        # Edges that lost all lines keep their original narrow range (set by find_sql_range).
        # Every edge must have sql_range so clicking it shows the corresponding SQL.
    
    return edges


# ── Convenience: drop-in replacement for old _estimate_sql_range ─────

def find_sql_range(edge_data: dict, sql_text: str) -> Optional[list]:
    """
    Drop-in replacement for the old _estimate_sql_range function.
    
    Args:
        edge_data: dict with edge metadata (same as before)
        sql_text: full SQL script text (or list of lines)
    
    Returns:
        [start_line, start_col, end_line, end_col] or None
    """
    if isinstance(sql_text, list):
        sql_text = '\n'.join(sql_text)
    
    finder = SqlRangeFinder(sql_text)
    return finder.find(edge_data)
