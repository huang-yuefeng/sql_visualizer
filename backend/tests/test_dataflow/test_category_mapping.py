"""Test that edge types map to correct 7 visual categories."""
import pytest
import sys
sys.path.insert(0, '/home/huangyf/work/sql_visualizer/backend')
from app.services.dataflow_service import _get_category, CATEGORY_MAP

VALID_CATEGORIES = {"copy", "compute", "aggregate", "filter", "combine", "write", "structure"}


class TestCategoryMapping:
    """Verify edge type → 7-category mapping."""

    def test_all_13_edge_types_have_category(self):
        """Every edge type must map to a valid category."""
        expected_types = {
            "REF", "TRANSFORM", "COMPUTED", "AGGREGATE", "WINDOW",
            "FILTER", "JOIN", "INDIRECT", "CORRELATED",
            "SET_OP", "SUBQUERY",
            "DML",
            "SCHEMA", "ALIAS", "SUBSET", "TABLE_FLOW",
        }
        for et in expected_types:
            cat = _get_category(et)
            assert cat in VALID_CATEGORIES, f"{et} → {cat} not valid"
    
    def test_ref_is_copy(self):
        assert _get_category("REF") == "copy"

    def test_transform_is_compute(self):
        assert _get_category("TRANSFORM") == "compute"
        assert _get_category("COMPUTED") == "compute"

    def test_aggregate_is_aggregate(self):
        assert _get_category("AGGREGATE") == "aggregate"
        assert _get_category("WINDOW") == "aggregate"

    def test_filter_is_filter(self):
        for et in ["FILTER", "JOIN", "INDIRECT", "CORRELATED"]:
            assert _get_category(et) == "filter", f"{et} should be filter"

    def test_combine_is_combine(self):
        for et in ["SET_OP", "SUBQUERY"]:
            assert _get_category(et) == "combine", f"{et} should be combine"

    def test_dml_is_write(self):
        assert _get_category("DML") == "write"

    def test_structure_is_structure(self):
        for et in ["SCHEMA", "ALIAS", "SUBSET", "TABLE_FLOW"]:
            assert _get_category(et) == "structure", f"{et} should be structure"

    def test_unknown_edge_type_defaults_to_structure(self):
        assert _get_category("UNKNOWN_TYPE") == "structure"
        assert _get_category("") == "structure"

    def test_no_duplicate_categories_in_map(self):
        """Each edge type maps to exactly one category."""
        seen = {}
        for et, cat in CATEGORY_MAP.items():
            seen[et] = cat
        assert len(seen) == len(CATEGORY_MAP), "Duplicate edge types in CATEGORY_MAP"

    def test_all_categories_used(self):
        """All 7 categories should be reachable."""
        used = set(CATEGORY_MAP.values())
        assert VALID_CATEGORIES == used, f"Unused categories: {VALID_CATEGORIES - used}"

    def test_category_map_is_complete(self):
        """CATEGORY_MAP should have exactly the expected edge types."""
        expected = {
            "REF", "TRANSFORM", "COMPUTED", "AGGREGATE", "WINDOW",
            "FILTER", "JOIN", "INDIRECT", "CORRELATED",
            "SET_OP", "SUBQUERY",
            "DML",
            "SCHEMA", "ALIAS", "SUBSET", "TABLE_FLOW",
        }
        assert set(CATEGORY_MAP.keys()) == expected
