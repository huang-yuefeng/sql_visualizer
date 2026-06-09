"""Pytest configuration and shared fixtures."""

import sys
from pathlib import Path

import pytest

# Add backend/ to the import path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

TEST_DATA_DIR = Path(__file__).resolve().parent / "test_data"
SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "samples"


def read_test_sql(filename: str) -> str:
    """Read a SQL test fixture file."""
    path = TEST_DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Test fixture not found: {path}")
    return path.read_text()


def read_sample_sql(filename: str) -> str:
    """Read a SQL sample file from the samples directory."""
    path = SAMPLES_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Sample not found: {path}")
    return path.read_text()


@pytest.fixture
def sample_fin_query1() -> str:
    """GPS financial query 1: reconciliation."""
    return read_sample_sql("financial/fin_query1_reconciliation.sql")


@pytest.fixture
def sample_fin_query2() -> str:
    """GPS financial query 2: fee calculation."""
    return read_sample_sql("financial/fin_query2_fee_calculation.sql")


@pytest.fixture
def sample_fin_query3() -> str:
    """GPS financial query 3: account balance."""
    return read_sample_sql("financial/fin_query3_account_balance.sql")


@pytest.fixture
def sample_fin_query4() -> str:
    """GPS financial query 4: merge upsert."""
    return read_sample_sql("financial/fin_query4_merge_upsert.sql")


@pytest.fixture
def sample_fin_query5() -> str:
    """GPS financial query 5: union risk report."""
    return read_sample_sql("financial/fin_query5_union_risk_report.sql")


@pytest.fixture
def sample_tables_financial() -> str:
    """GPS financial DDL."""
    return read_sample_sql("financial/tables_financial.sql")
