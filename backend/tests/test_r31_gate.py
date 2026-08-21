"""R31 login gate — verified in a SUBPROCESS with REQUIRE_LOGIN=true.

The gate is a module-import-time config read (app.config / main.py /
workspace.py), so it can only be exercised in a fresh process. Running the
probe as a subprocess keeps the main suite (gate OFF) untouched and gives
the gate-on behavior a real, isolated test.
"""

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROBE = Path(__file__).resolve().parent / "r31_probe.py"


def test_login_gate_contract():
    env = dict(os.environ)
    env["REQUIRE_LOGIN"] = "true"
    env["PYTHONPATH"] = str(BACKEND_DIR)
    r = subprocess.run(
        [sys.executable, str(PROBE)],
        capture_output=True, text=True, env=env, timeout=180,
    )
    assert r.returncode == 0, f"gate probe failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    assert "GATE PROBE PASS" in r.stdout
