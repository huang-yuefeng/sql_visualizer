# L2 Snapshot Changelog

The L2 snapshot gate (`backend/tests/test_l2_snapshot.py`) pins committed
byte-identical L2 output under `backend/tests/snapshots/`. Rebaselining is
deliberate (`L2_SNAPSHOT_UPDATE=1 python3 -m pytest tests/test_l2_snapshot.py -q`),
so every repin should be recorded here with the reason. The gate is
self-consistency only — a repin proves the new baseline reproduces, NOT that it
is correct; each baseline also needs a one-time human sanity check (see the
module docstring in `test_l2_snapshot.py`).

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
