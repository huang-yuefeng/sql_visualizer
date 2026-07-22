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
            else:
                # Can't find exact match — fall back to line estimation
                start_line = 1
                end_line = len(self.lines)
            
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
        "TABLE_FLOW":[r"\bINSERT\s+INTO\b.*\bSELECT\b", r"\bFROM\b", r"\bINTO\b"],
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
        "TABLE_FLOW": {"INSERT": 3, "INTO": 3},
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
    
    def __init__(self, statement: SqlStatement, matched_line: int, all_lines: list):
        self.statement = statement
        self.matched_line = matched_line  # 0-based index in all_lines
        self.all_lines = all_lines
    
    def build(self) -> SqlRange:
        """Build the final range, extending matched line to statement boundaries."""
        # Start from the matched line, extend backward to statement start
        start_line = self.matched_line
        
        # Backward: go until statement start or definite new-statement keyword
        while start_line > self.statement.start_line - 1:
            prev = self.all_lines[start_line - 1].strip().upper()
            if not prev or prev.startswith('--'):
                # Comment/blank: check if previous line starts new statement
                if start_line - 1 > self.statement.start_line - 1:
                    start_line -= 1
                    continue
                break
            # Stop at definite statement starters
            if any(prev.startswith(kw) for kw in self._STMT_START_KW):
                break
            start_line -= 1
        
        # Forward: go until statement end
        end_line = self.matched_line
        while end_line < self.statement.end_line - 1:
            nxt = self.all_lines[end_line + 1].strip()
            if nxt.rstrip().endswith(';'):
                end_line += 1
                break
            if not nxt or nxt.startswith('--'):
                # Check if line after blank/comment starts a new statement
                if end_line + 2 < len(self.all_lines):
                    after = self.all_lines[end_line + 2].strip().upper()
                    if any(after.startswith(kw) for kw in self._STMT_START_KW):
                        break
                end_line += 1
                continue
            end_line += 1
        
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
        builder = RangeBuilder(statement, best_line, self.lines)
        return builder.build().to_list()


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
