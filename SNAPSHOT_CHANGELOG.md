# L2 Snapshot Changelog

The L2 snapshot gate (`backend/tests/test_l2_snapshot.py`) pins committed
byte-identical L2 output under `backend/tests/snapshots/`. Rebaselining is
deliberate (`L2_SNAPSHOT_UPDATE=1 python3 -m pytest tests/test_l2_snapshot.py -q`),
so every repin should be recorded here with the reason. The gate is
self-consistency only — a repin proves the new baseline reproduces, NOT that it
is correct; each baseline also needs a one-time human sanity check (see the
module docstring in `test_l2_snapshot.py`).

## v3.3.170 (commit `7f335c4`)

Three snapshots rebaselined for the OCR-repaired samples (PL/EAST5/Digitallending
replaced with cross-corroborated reconstructions; EAST5 gained alias `a` @141,
3 partition ALTERs @171-173 and a previously-dropped WPB_CDT_Digitallending
ALTER @175, shifting the rrcdm write leg TOP7→TOP11 — canonical rows E5D4/RDE3
re-pinned in the same commit). Every hunk was audited 1:1 against the SQL diffs
(snapshot audit 2026-08-27: no extractor regression masked):

| Snapshot | Change | Driver |
|----------|--------|--------|
| `l2_snapshot_00_BDM_ACC_LOAN_INFO_Digitallending.sql.json` | 449→444 nodes, 669→659 edges | DL: 4 duplicate projections commented out (@110-111/147/167/176), `CUST_TYPE ('I','3')→('I','J')` (RFN-corroborated) |
| `l2_snapshot_01_BDM_ACC_LOAN_INFO_PL.sql.json` | 302→303 nodes, 316→317 edges | PL: ~40 identifier renames to sibling-corroborated canonical spellings (GREENLOAN_TYPE, LOAN_EX_GU_NO, …) |
| `l2_snapshot_04_EAST5_STZFXXB_M.sql.json` | 137→129 nodes, 164→164 edges | EAST5: alias `a` now declared (a.-qualified fields move to bdm_acc_entrusted_payment), +4 ⟐output VTs from the added ALTER statements, duplicate TAG_*/RESERVED_* twins collapse 2→1 |

## v3.3.164 (commit `0bc0b54`)

Three snapshots were repinned inside the monolithic v3.3.164 release commit
(`0bc0b54 [release] v3.3.164`) with no per-repin note. Each was rebaselined for
v3.3.164 — the L2 output intentionally changed in that release and the baselines
were regenerated to match. (No specific dates/bugs are claimed here; the only
auditable fact is that these three files changed in `0bc0b54`.)

| Snapshot | Script | Rationale |
|----------|--------|-----------|
| `l2_snapshot_00_BDM_ACC_LOAN_INFO_Digitallending.sql.json` | `BDM_ACC_LOAN_INFO_Digitallending.sql` | Rebaselined for v3.3.164 (intentional L2 output change). |
| `l2_snapshot_02_BDM_ACC_LOAN_INFO_RFN.sql.json` | `BDM_ACC_LOAN_INFO_RFN.sql` | Rebaselined for v3.3.164 (intentional L2 output change). |
| `l2_snapshot_04_EAST5_STZFXXB_M.sql.json` | `EAST5_STZFXXB_M.sql` | Rebaselined for v3.3.164 (intentional L2 output change). |

## How to add an entry

When you rebaseline one or more snapshots, append a dated section listing the
exact snapshot file(s) and a one-line rationale (the feature/fix that changed
the output, or "regenerated for <version>" when the change is a pure repin).
Keep rationales honest — never fabricate dates or bug numbers.
