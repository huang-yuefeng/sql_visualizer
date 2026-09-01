# Flow-only view: the complete edge show/hide rules

> Every rule that decides whether an edge appears in the L2 flow-only view, with examples
> from the flagship scripts, and the confusing ones labeled. Written 2026-09-01 for the
> user's review; the two ⚡ ruling items gate the jaccard benchmark's final state.

## The foundation: two ways an edge earns its place

| # | An edge is shown if… | Example |
|---|---|---|
| **V** | **The searched field's VALUE travels on it** — the field is read, computed, or written | `p1.lending_ref` in a SELECT → written into `bdm_acc_loan_info_sup` |
| **S** | **It's structural skeleton** — it positions the boxes the value lives in (table/CTE/alias compounds, FROM/JOIN headers, belongs-to "field X exists here") | `FROM bdm_acc_loan_info p1` (the header edge) |

Everything below refines these two ideas.

---

## 1. SEED rules — where the closure starts

| # | Rule | Shown? | Example |
|---|---|---|---|
| 1a | Occurrences of the searched field on the searched table's compounds seed the closure | ✅ | Search `lending_ref` → the `p1.lending_ref` chips on `bdm_acc_loan_info` |
| 1b | #399 alias expansion: a TVF/alias/CTE whose projection carries the field also seeds | ✅ | `v_bdm_customer_all('...') a` — searching `a.cust_no` seeds through the TVF |
| 1c | Same-name occurrences on OTHER tables' compounds do **not** seed | ❌ | Searching `bdm_acc_loan_info.data_dt`: the `c/d/e.data_dt` chips of `bdm_pub_branch` / `BDM_ACC_INTERNAL_COUNTERPARTY` do not seed — **(RC-A class, fixed by the R-GATE)** |

---

## 2. VALUE rules — edges that carry the field's value

| # | Rule | Shown? | Example |
|---|---|---|---|
| 2a | **Reads**: a projection/expression reading the field's value | ✅ | `SELECT p1.lending_ref` @163 |
| 2b | **Writes**: the value written into a target table | ✅ | `INSERT OVERWRITE bdm_acc_loan_info_sup ... p1.lending_ref` |
| 2c | **Computes**: the value inside an expression feeding an output | ✅ | `CONCAT(p2.poctcd, ...) = p1.lending_ref` @41 |
| 2d | **Filters on the field**: a predicate selecting rows by it | ✅ | `WHERE p1.data_dt = '$(load_date)'` |
| 2e | **Join keys on the field**: the join operand IS the field | ✅ | `ON p6.lending_ref = p1.lending_ref` @156 |
| 2f | **Group/window keys on the field**: it decides grouping/ranking | ✅ | `GROUP BY ... product` @246; `ROW_NUMBER() OVER(PARTITION BY p1.acnw)` @64 — the **Reappears** stage |
| 2g | A statement writes a column **named** like the field but the **value is a literal/constant** | ❌ ⚡ | The job-log: `INSERT INTO rrcdm_job_log_exec_par(data_dt, ...) SELECT '$(load_date)' AS data_dt, COUNT(1)...` — see ruling 7-A |

---

## 3. SIBLING rules — other fields written by the same statement

| # | Rule | Shown? | Example |
|---|---|---|---|
| 3a | A sibling field's **belongs-to** edge (structural fact: it exists on this line) | ✅ (skeleton) | `reserved_field8` written at L82 next to `lending_ref` — its belongs-to edge stays |
| 3b | A sibling field's **value legs** (its write/read/compute edges) | ❌ | Searching `lending_ref`: `reserved_field8`'s write leg, read leg, and output-membership edges are dropped — **(the field-involvement rule, user-ruling #48; fixed 4 over-included edges)** |
| 3c | The sibling field's **chip** in the closure | ❌ (R46a) | Searching `bdm_acc_loan_info.data_dt`: the `b/c/d/e.data_dt` chips are ordinary nodes |

---

## 4. TWINS rules — the same field at many lines

| # | Rule | Shown? | Example |
|---|---|---|---|
| 4a | Each occurrence lights at its **own line** | ✅ | `charge_department`'s CASE arms: exactly {54,55,56,66,68,70} |
| 4b | **JOIN-ON AND-continuation legs** (family-4 twins) | ✅ | `AND b.lending_ref = a.lending_ref` @144, `AND b.org_no = c.org_no` @147 |
| 4c | A line already anchored by a surviving var — no duplicate | ❌ | The L82 NVL read: anchored once |
| 4d | A twin with **no owner evidence** is not minted | ❌ | `d.org_no` @L150 — the line's owner is `b.org_no`'s (already served) |

---

## 5. FOLD rules — which carrier represents the group

| # | Rule | Shown? | Example |
|---|---|---|---|
| 5a | **Multi-anchor**: N occurrences joining the same target at N lines → N edges | ✅ | `lending_ref` joining `loan_final` at 95/117/150/156 → 4 JOIN edges **(RC-B, fixed)** |
| 5b | **Fix H keeper-line**: a carrier at the chip's own line wins | ✅ | — |
| 5c | **Line-0 guard**: a carrier with no line never anchors | ❌ | The TVF-alias class — now fixed to carry real lines (M-T1) |
| 5d | **Claimed-together**: a group whose line another relationship claims earns no extra edge | ❌ | The LFS108 NOT-IN filter |
| 5e | **Cross-statement instance duplication**: an occurrence with a qualifying owner instance is not duplicated onto a different statement's instance | ❌ **(J2 fixing — defect A)** | SUP_M @202: the `data_dt` occurrence is owned by `p2@199` (the join) — not duplicated onto the L223 job-log instance |
| 5f | **Foreign-owner guessed fold**: an occurrence is never re-parented onto the searched compound without owner evidence | ❌ **(J2 fixing — defect B)** | PL @250: `T_BRANCH.data_dt`'s edges served as `bdm_acc_loan_info.data_dt` — the FSB phantom class |

---

## 6. GATE rules — the value-cone excludes what the value never reaches

| # | Rule | Shown? | Example |
|---|---|---|---|
| 6a | **Cross-table same-name seeds** | ❌ | Searching `bdm_acc_loan_info.data_dt`: the `c/d/e.data_dt` chips excluded — **(RC-A, fixed)** |
| 6b | **Foreign statement trunks**: a statement that doesn't carry the field's value doesn't enter | ❌ | The job-log DML trunk drops from `lending_ref`'s closure; `rrcdm ↓ EAST5` stays 3/3 |
| 6c | **Foreign-owner folds** respected | ❌ | PL @250: edges attribute to `T_BRANCH`, never the searched compound — **(J2 fixing)** |

---

## ⚡ 7. THE RULING ITEMS — where the rules conflict

### ⚡ 7-A. The job-log continuation (R29 vs the field-involvement rule) — BLOCKING

```sql
L155:  INSERT OVERWRITE TABLE bdm_acc_loan_info_sup ...   ← the value lands here ✅
L211:  INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt, ...)
L212:  SELECT '$(load_date)' AS data_dt, COUNT(1) ...     ← NO field value — a log/count
L222:  FROM bdm_acc_loan_info_sup
```

- **R29 (2026-08-12) says: SHOWN** — "the graph must be one connected flow": without the bridge it breaks into two islands.
- **The field-involvement rule says: NOT shown** — the log-write carries a count + literals, no field value. FSA measured: **76 fields' stories claimed "consumed @179"** by this same log-write.
- **Currently the engine is inconsistent**: EAST5's log-write trunk is shown; SUP_M/iiapty's is dropped.
- **Decides**: 2 jaccard cases, 2 L1 doc tests, the ground-truth docs, and ~191 continuation legs across the flagships.

### ⚡ 7-B. The own-table co-filter sibling (J12-20 pin)

PL @265: `AND charge_department = 'OPS_CLBS_PLoan'` — an edgeless co-filter sibling on the searched table's own compound. J12-20 pinned it as a documented closure member; the DL mirror serves it; but the PL **filtered** view drops it (a filtered-path under-emission). **(J2 fixing.)**

### ⚡ 7-C. The sibling same-name REF edge (`src_b.dt` → `src_a.dt`'s closure)

The extractor builds a same-name REF edge between two tables' same-named columns; the walker can ride it into the sibling's closure. Under the field-involvement principle this is other-field flow → the traversal excludes it. (The *edge* is a real extraction fact — the question is whether the *walker* traverses it.)

### ⚡ 7-D. The ⟐output membership edges of sibling chips

When a sibling chip is admitted (co-written projection), its ⟐output membership SCHEMA edge rides along. J1's rule drops sibling VALUE edges but keeps sibling belongs-to/membership — the exact boundary needs the value-cone ruling (the full R-GATE, v3.3.195).

**UPDATE 2026-09-01 (evening): 7-D now BLOCKS something concrete.** The
determinism fix (canonical dependency order, killing the PYTHONHASHSEED
instability the snapshot harness documents) was proven end-to-end and
reverted at the gate for exactly this reason: with the canonical order, the
walk admits ONE sibling chip + one routed REF edge the natural-order walk
did not (PL filtered, `data_dt` seed: `CHARGE_DEPARTMENT`@L19, precision
N 1.0000 → 0.875). Whether that sibling membership belongs in the closure
IS this ruling. The full landing recipe is preserved in the xfail reason of
`backend/tests/test_l2_determinism.py::test_l2_full_view_is_byte_identical
_across_hash_seeds`; landing after the 7-D ruling is a ~15-minute job.

---

# Summary — the decision tree

```
Is the edge about the SEARCHED field's VALUE?
├── YES → shown (read/write/compute/filter/join-key/group-key/window-key/
│         occurrence twin/AND-leg, each at its own line)
├── Is it STRUCTURAL SKELETON (headers, belongs-to, containers, aliases) → shown as context
├── Is it ANOTHER FIELD's value flow → dropped (the field-involvement rule)
├── Is it a statement that only NAMES the field but writes literals
│   (the job-log) → ⚡ RULING 7-A PENDING
└── Is it a same-name chip on another table → not seeded (RC-A, fixed)
```

# Rules provenance (which team/change landed which rule)

| Rule group | Landed in | By |
|---|---|---|
| Seeds (W1 + #399 alias expansion) | lineage.py W1 | R29/#399 |
| Value edges (FIELD_LAND/D2/W2-W6b) | lineage.py | R18–R44 |
| Occurrence twins (families 1-3) | variable_extractor_v2 (.9-.12) | R44/R45/G7 |
| JOIN-ON AND-legs + Phase 9 | dependency_graph (.12) | F-E1/V5 |
| Multi-anchor fold + Fix H + line-0 + LFS108 | l2_builder `_combine_edges` | G8/AD2/J2 |
| Field-involvement admission (sibling value legs drop) | l2_builder `_apply_field_involvement` | J1 (#48) |
| R-GATE value-cone + recall guard + bare-column seeds | lineage `_VALUE_CONE_GATE`/`_OWNERLESS_SEED` | V4/AD3/FSC |
| is_target scoping (searched entities ∪ receiving write targets) | l2_builder `_scope_target_stamp` | R46a/AD3 |
| Casing invariance (`_fold`, 3 engines) | lineage/l1_builder/dataflow_service | H7/R46e |
| Model persistence beside graph cache | graph_service `model_{key}.json` | V6/FSC-2 |
