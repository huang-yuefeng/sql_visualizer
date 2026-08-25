// Shared typo-tolerant name matcher for autocomplete popups (FilterPanel).
// Mirrors backend folder_index_service.autocomplete(): case-insensitive
// substring primary; when that yields <2 hits, add Levenshtein-distance-<=1
// fallback, ranked exact > prefix > distance-1, capped at MAX (20).

const MAX = 20;

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
  if (!q) return (names || []).slice().sort().slice(0, MAX);
  const query = q.toLowerCase();
  const sub = (names || [])
    .filter((n) => n.toLowerCase().includes(query))
    .sort();
  if (sub.length >= 2) return sub.slice(0, MAX);
  const exact = (names || []).filter((n) => n.toLowerCase() === query).sort();
  const prefix = (names || [])
    .filter((n) => n.toLowerCase().startsWith(query))
    .sort();
  const seen = new Set([...exact, ...prefix].map((s) => s.toLowerCase()));
  const dist1 = (names || [])
    .filter((n) => {
      const nl = n.toLowerCase();
      if (seen.has(nl)) return false;
      return levenshteinLe1(nl, query);
    })
    .sort();
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

export default filterNames;
