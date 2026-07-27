# SQL Segment Accuracy — Mathematical Verification Metrics

> **Date:** 2026-07-22 | **Version:** 3.3.47

---

## Current Weak Checks (NOT sufficient)

| Check | Threshold | Problem |
|-------|-----------|---------|
| Comment-only | All lines start with `--` | Too weak — catches only the worst case |
| Span >50 lines | `end_line - start_line > 50` | Arbitrary — what if the real SQL is 60 lines? |
| Content <5 chars | Total content too short | Misses narrow-but-correct ranges |

---

## Proposed: Multi-Factor Scoring Function

For each edge with `sql_range = [L_start, L_end]` and `edge_type`, score from 0-100:

```
Score = w1 * KeywordRelevance + w2 * EntityPresence + w3 * Specificity + w4 * SpanCorrectness
```

Where weights: `w1=0.35, w2=0.25, w3=0.25, w4=0.15`

### Factor 1: Keyword Relevance (0-100)

Does the highlighted segment contain keywords matching the edge type?

```python
EDGE_KEYWORDS = {
    "JOIN":     ["JOIN", "LEFT JOIN", "RIGHT JOIN", "INNER JOIN", "OUTER JOIN", "CROSS JOIN"],
    "FILTER":   ["WHERE", "HAVING", "AND", "OR", "BETWEEN", "IN (", "NOT IN"],
    "AGGREGATE":["SUM(", "COUNT(", "AVG(", "MIN(", "MAX(", "GROUP BY"],
    "WINDOW":   ["OVER (", "PARTITION BY", "ROW_NUMBER()", "RANK()", "LAG(", "LEAD("],
    "TRANSFORM":["CAST(", "COALESCE(", "CONCAT(", "UPPER(", "LOWER(", "ROUND("],
    "DML":      ["INSERT ", "UPDATE ", "DELETE ", "MERGE "],
    "TABLE_FLOW":["FROM ", "INTO ", "SELECT "],
    "CASE":     ["CASE ", "WHEN ", "THEN ", "ELSE ", "END"],
    "REF":      [],  # column references — use entity presence
    "SUBQUERY": ["SELECT ", "FROM ("],
    "UNION":    ["UNION ", "UNION ALL"],
    "CTE":      ["WITH ", "AS ("],
}
```

```python
def keyword_relevance(sql_segment, edge_type):
    types = [t.strip() for t in edge_type.split(",")]
    keywords = []
    for t in types:
        keywords.extend(EDGE_KEYWORDS.get(t, []))
    if not keywords:
        return 50  # neutral — no keywords to check
    
    hits = sum(1 for kw in keywords if kw.upper() in sql_segment.upper())
    density = hits / max(len(sql_segment.split('\n')), 1)
    return min(100, density * 25 + 25)  # scale: 0 hits→25, 4 hits/line→100
```

### Factor 2: Entity Presence (0-100)

Does the segment contain the source/target table or column names from the edge?

```python
def entity_presence(sql_segment, source_label, target_label):
    entities = []
    for label in (source_label, target_label):
        if label:
            # Extract table/column names, skip dots
            parts = label.replace('.', ' ').replace(',', ' ').split()
            entities.extend([p for p in parts if len(p) > 1])
    
    if not entities:
        return 50  # neutral
    
    hits = sum(1 for e in entities if e.upper() in sql_segment.upper())
    return min(100, hits / len(entities) * 100)
```

### Factor 3: Specificity (0-100)

How precise is the range? A 1-line hit on exactly the JOIN line scores higher than a 50-line range containing JOIN somewhere.

```python
def specificity(span_lines, edge_type):
    """
    Specificity = how concentrated the relevant content is.
    High specificity = narrow range, high keyword density.
    Low specificity = wide range, low keyword density.
    """
    if span_lines == 0: return 0
    
    types = [t.strip() for t in edge_type.split(",")]
    keywords = []
    for t in types:
        keywords.extend(EDGE_KEYWORDS.get(t, []))
    
    if not keywords:
        # No keywords: specificity based on range tightness
        return max(0, 100 - span_lines * 5)
    
    keyword_density = sum(1 for kw in keywords if any(kw.upper() in l.upper() for l in sql_lines)) / span_lines
    return min(100, keyword_density * 30 + 40)
```

### Factor 4: Span Correctness (0-100)

The range shouldn't be too narrow (1 char) or too wide (entire file).

```python
def span_correctness(span_lines, total_file_lines):
    """
    Optimal range: 2-20 lines for most operations.
    Penalize: 1 line (too narrow — likely just a column name),
             >50% of file (too wide — likely not bounded correctly).
    """
    if span_lines == 0: return 0
    if span_lines == 1: return 30  # too narrow
    if span_lines <= 5: return 90  # tight, likely correct
    if span_lines <= 20: return 80  # moderate
    if span_lines <= 50: return 60  # wide
    ratio = span_lines / max(total_file_lines, 1)
    if ratio > 0.5: return max(0, 40 - int(ratio * 60))  # >50% of file
    return 50
```

---

## Overall Verdict

```python
def evaluate_edge(edge, sql_lines):
    score = (0.35 * keyword_relevance(segment, edge.type) +
             0.25 * entity_presence(segment, edge.source_label, edge.target_label) +
             0.25 * specificity(span, edge.type) +
             0.15 * span_correctness(span, len(sql_lines)))
    
    if score >= 70: return "PASS"
    elif score >= 40: return "PARTIAL"
    else: return "FAIL"
```

---

## Usage

```python
# Run against all edges in a dataset:
results = []
for edge in l2_edges:
    score = evaluate_edge(edge, sql_lines)
    results.append({"edge": edge.id, "type": edge.edge_type, "score": score, "verdict": verdict(score)})

# Summary:
pass_rate = sum(1 for r in results if r["verdict"] == "PASS") / len(results)
print(f"Accuracy: {pass_rate:.0%} ({pass_count}/{total} edges)")
```
