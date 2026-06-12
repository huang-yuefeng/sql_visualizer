"""Verify all 15 variable types have styling entries in both backend and frontend.

A type missing from the Cytoscape stylesheet (graphStyles.js) will render as
a default grey ellipse regardless of the shape/color in the node data.
"""

import re
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
sys.path.insert(0, str(BACKEND_DIR))

from app.models.variable import VariableType
from app.services.graph_service import NODE_STYLES


ALL_TYPES = {t.value for t in VariableType}
assert len(ALL_TYPES) == 15, f"Expected 15 types, got {len(ALL_TYPES)}"


# ── Backend: graph_service.py NODE_STYLES ──────────────────────────────

class TestBackendNodeStyles:
    """Every VariableType must have an entry in graph_service.NODE_STYLES."""

    def test_all_types_in_node_styles(self):
        styled_types = set(NODE_STYLES.keys())
        missing = ALL_TYPES - styled_types
        assert not missing, (
            f"Types missing from graph_service.NODE_STYLES: {missing}\n"
            f"Styled: {sorted(styled_types)}"
        )

    def test_no_extra_styles(self):
        """NODE_STYLES should not have entries for non-existent types."""
        extra = set(NODE_STYLES.keys()) - ALL_TYPES
        assert not extra, f"Extra NODE_STYLES keys (not in VariableType): {extra}"

    def test_every_style_has_required_fields(self):
        """Every style must have shape, color, and size."""
        for type_val, style in NODE_STYLES.items():
            assert "shape" in style, f"{type_val}: missing 'shape'"
            assert "color" in style, f"{type_val}: missing 'color'"
            assert "size" in style, f"{type_val}: missing 'size'"


# ── Frontend: graphStyles.js Cytoscape selectors ───────────────────────

def _parse_cytoscape_selectors(js_path: Path) -> set[str]:
    """Extract all variable_type values from Cytoscape node selectors."""
    text = js_path.read_text()
    # Match: selector: 'node[variable_type="<name>"]'
    pattern = r'node\[variable_type="(\w+)"\]'
    return set(re.findall(pattern, text))


def _parse_frontend_colors(jsx_path: Path) -> set[str]:
    """Extract all type keys from the App.jsx color map (const C)."""
    text = jsx_path.read_text()
    # Match the const C = { ... } block
    m = re.search(r'const C\s*=\s*\{([^}]+)\}', text)
    if not m:
        return set()
    block = m.group(1)
    # Extract keys:  key:'#COLOR'  or  key:'#COLOR',
    keys = set(re.findall(r"(\w+)\s*:", block))
    # Filter out non-type keys (if any)
    return {k for k in keys if k in ALL_TYPES or True}  # keep all for checking


class TestFrontendNodeStyles:
    """Every VariableType must have a Cytoscape CSS selector in graphStyles.js."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.js_path = FRONTEND_DIR / "src" / "utils" / "graphStyles.js"
        self.jsx_path = FRONTEND_DIR / "src" / "App.jsx"

    def test_all_types_in_cytoscape_selectors(self):
        """graphStyles.js must have a selector for every node type."""
        if not self.js_path.exists():
            pytest.skip("frontend not available")
        cyto_types = _parse_cytoscape_selectors(self.js_path)
        missing = ALL_TYPES - cyto_types
        assert not missing, (
            f"Types missing from graphStyles.js Cytoscape selectors: {missing}\n"
            f"Found: {sorted(cyto_types)}\n"
            f"These types will render as default grey ellipses!"
        )

    def test_no_stale_cytoscape_selectors(self):
        """graphStyles.js should not have selectors for removed types."""
        if not self.js_path.exists():
            pytest.skip("frontend not available")
        cyto_types = _parse_cytoscape_selectors(self.js_path)
        stale = cyto_types - ALL_TYPES
        # 'script' is the meta-graph node type, not a VariableType — allow it
        stale_allowed = {"script"}
        stale = stale - stale_allowed
        assert not stale, f"Stale selectors in graphStyles.js: {stale}"

    def test_all_types_in_frontend_colors(self):
        """App.jsx const C must have a color entry for every node type."""
        if not self.jsx_path.exists():
            pytest.skip("frontend not available")
        frontend_types = _parse_frontend_colors(self.jsx_path)
        missing = ALL_TYPES - frontend_types
        assert not missing, (
            f"Types missing from App.jsx color map (const C): {missing}"
        )

    def test_all_types_in_frontend_node_shapes(self):
        """App.jsx NODE_SHAPES must have an entry for every node type."""
        if not self.jsx_path.exists():
            pytest.skip("frontend not available")
        text = self.jsx_path.read_text()
        m = re.search(r'const NODE_SHAPES\s*=\s*\{([^}]+)\}', text)
        assert m, "Could not find NODE_SHAPES in App.jsx"
        block = m.group(1)
        shape_types = set(re.findall(r"(\w+)\s*:", block))
        missing = ALL_TYPES - shape_types
        assert not missing, (
            f"Types missing from App.jsx NODE_SHAPES: {missing}"
        )

    def test_all_types_in_frontend_filter(self):
        """App.jsx VT filter array must have an entry for every node type."""
        if not self.jsx_path.exists():
            pytest.skip("frontend not available")
        text = self.jsx_path.read_text()
        # Extract all {value:'<type>',...} entries from the VT array
        vt_types = set(re.findall(r"\{value:'(\w+)'", text))
        missing = ALL_TYPES - vt_types
        # 'view' might be missing from old filter arrays — check
        assert not missing, (
            f"Types missing from App.jsx VT filter array: {missing}"
        )


# ── Integration: verify shape assignment ──────────────────────────────

class TestShapeAssignment:
    """Verify that each type's shape is correctly passed through the pipeline."""

    def test_every_type_has_valid_shape_name(self):
        """Shapes should be valid Cytoscape.js shape names."""
        valid_shapes = {
            "rectangle", "round-rectangle", "ellipse", "triangle",
            "diamond", "hexagon", "pentagon", "parallelogram", "vee",
            "star", "octagon", "polygon",
        }
        for type_val, style in NODE_STYLES.items():
            shape = style.get("shape", "")
            assert shape in valid_shapes, (
                f"{type_val}: shape '{shape}' is not a valid Cytoscape.js shape.\n"
                f"Valid: {sorted(valid_shapes)}"
            )

    def test_table_types_have_large_size(self):
        """Table-like types (table, view, cte, virtual_table, merge_target)
        should be larger than computed types."""
        table_like = {"table", "view", "cte", "virtual_table", "merge_target"}
        for type_val in table_like:
            style = NODE_STYLES.get(type_val, {})
            size = style.get("size", 0)
            assert size >= 45, (
                f"{type_val}: table-like type should have size ≥45, got {size}"
            )

    def test_column_types_have_small_size(self):
        """Column types should be small (they're leaf nodes)."""
        for type_val in ["column", "cte_column"]:
            style = NODE_STYLES.get(type_val, {})
            size = style.get("size", 0)
            assert size <= 35, (
                f"{type_val}: column type should have size ≤35, got {size}"
            )
