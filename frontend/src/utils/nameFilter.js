// Shared typo-tolerant name matcher for autocomplete popups (FilterPanel).
// Mirrors backend folder_index_service.autocomplete(): case-insensitive
// substring primary; when that yields <2 hits, add Levenshtein-distance-<=1
// fallback, ranked exact > prefix > distance-1, capped at MAX (20).

const MAX = 20;

// Case-insensitive comparator for autocomplete ranking — a bare .sort()
// orders by code unit (uppercase sorts before lowercase), which makes the
// ranking depend on the input case. sensitivity:'base' folds case (and
// accents) so the order is stable regardless of how the names are cased.
function ciCompare(a, b) {
  return String(a).localeCompare(String(b), undefined, { sensitivity: 'base' });
}

// Levenshtein distance <= 1 (fast: length gate + bounded DP).
export function levenshteinLe1(a, b) {
  if (a === b) return true;
  if (Math.abs(a.length - b.length) > 1) return false;
  if (a.length > b.length) { const t = a; a = b; b = t; }
  let prev = Array.from({ length: a.length + 1 }, (_, i) => i);
  for (let j = 1; j <= b.length; j++) {
    const cur = [j];
    let rowMin = j;
    for (let i = 1; i <= a.length; i++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      const val = Math.min(prev[i] + 1, cur[i - 1] + 1, prev[i - 1] + cost);
      cur.push(val);
      if (val < rowMin) rowMin = val;
    }
    if (rowMin > 1) return false;
    prev = cur;
  }
  return prev[a.length] <= 1;
}

// Filter + rank `names` against the query (case-insensitive), max 20.
// Empty query → first 20 (alphabetical, matching backend sorted keys).
export function filterNames(names, q) {
  if (!q) return (names || []).slice().sort(ciCompare).slice(0, MAX);
  const query = q.toLowerCase();
  const sub = (names || [])
    .filter((n) => n.toLowerCase().includes(query))
    .sort(ciCompare);
  if (sub.length >= 2) return sub.slice(0, MAX);
  const exact = (names || []).filter((n) => n.toLowerCase() === query).sort(ciCompare);
  const prefix = (names || [])
    .filter((n) => n.toLowerCase().startsWith(query))
    .sort(ciCompare);
  const seen = new Set([...exact, ...prefix].map((s) => s.toLowerCase()));
  const dist1 = (names || [])
    .filter((n) => {
      const nl = n.toLowerCase();
      if (seen.has(nl)) return false;
      return levenshteinLe1(nl, query);
    })
    .sort(ciCompare);
  const out = [];
  const outSeen = new Set();
  for (const k of [...sub, ...exact, ...prefix, ...dist1]) {
    const kl = k.toLowerCase();
    if (!outSeen.has(kl)) {
      outSeen.add(kl);
      out.push(k);
    }
  }
  return out.slice(0, MAX);
}

// F5 (audit #383): case-insensitive name resolution for the search panel.
// Index keys carry the casing each script WROTE (TEMP_RFN vs temp_rfn —
// SQL identifiers are case-insensitive), while the backend search matches
// keys exactly (field_index.get(field)). A typed name in any casing must
// resolve to the canonical index key before the search is sent. Exact key
// wins; otherwise the case-insensitive equals are ranked with the same
// collation the dropdown uses and the first is taken (deterministic when
// several scripts wrote the same identifier in different cases). No hit →
// null — the caller shows the inline "not in the index" message.
export function resolveNameCi(names, typed) {
  if (!typed) return null;
  const list = names || [];
  const t = String(typed);
  if (list.includes(t)) return t;
  const query = t.toLowerCase();
  const hits = list.filter((n) => String(n).toLowerCase() === query)
    .sort(ciCompare);
  return hits.length > 0 ? hits[0] : null;
}

export default filterNames;
