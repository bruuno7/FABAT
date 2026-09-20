"""El ensayo no lee secretos, no abre producción y falla cerrado."""
from __future__ import annotations

import io
import json
import os
import socket
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import cast
from unittest.mock import patch

import httpx

from .operational_scenarios import (
    ROOT,
    InvariantFailure,
    fresh_output,
    offline,
    run_batch,
)
from .preflight import main, run_preflight


class PreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="preflight-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_ambient_secrets_and_production_path_cannot_enable_providers(self) -> None:
        production = self.root / "do-not-touch.sqlite"
        production.write_bytes(b"SYNTHETIC production sentinel; not a real database")
        marker = "synthetic-private-value-must-not-leak"
        environment = {"MANDO_OPERATIONAL_DB": str(production), "MANDO_EXTERNAL_DELIVERY": "1",
                       "TELEGRAM_BOT_TOKEN": marker, "HR_API_KEY": marker, "HR_SECRET": marker,
                       "HR_WORKFLOW_RAPIDO": marker, "HR_WORKFLOW_DISPATCH": marker,
                       "MANDO_PUBLIC_URL": "https://synthetic.invalid", "MANDO_ALLOWED_NUMBERS": marker}
        output = fresh_output(self.root / "safe")
        with (patch.dict(os.environ, environment),
              patch("dotenv.load_dotenv", side_effect=InvariantFailure("dotenv_forbidden"))):
            result = run_preflight(output, 17)
            self.assertEqual(os.environ["HR_API_KEY"], marker)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(production.read_bytes(), b"SYNTHETIC production sentinel; not a real database")
        self.assertNotIn(marker, (output / "preflight.json").read_text())
        self.assertNotIn(marker, (output / "demo-trace.json").read_text())
        self.assertTrue((output / "demo.sqlite").exists())

    def test_network_guard_blocks_http_and_socket(self) -> None:
        with offline():
            with self.assertRaises(InvariantFailure):
                httpx.post("https://synthetic.invalid")
            with self.assertRaises(InvariantFailure), socket.socket() as connection:
                connection.connect(("127.0.0.1", 9))

    def test_demo_failure_is_durable_and_cli_nonzero(self) -> None:
        output = self.root / "failed"
        stream = io.StringIO()
        with (patch("motor.server.preflight.demonstrate", side_effect=InvariantFailure("injected-regression")),
              redirect_stdout(stream)):
            status = main(["--seed", "17", "--output", str(output)])
        self.assertEqual(status, 1)
        result = json.loads((output / "preflight.json").read_text())
        self.assertFalse(result["ok"])
        self.assertIn("injected-regression", result["errors"])
        self.assertNotIn("Evidencias:", stream.getvalue())

    def test_output_must_be_new_outside_repo_and_never_overwrites(self) -> None:
        with self.assertRaises(ValueError):
            fresh_output(ROOT / "forbidden-artifacts")
        output = fresh_output(self.root / "existing")
        sentinel = output / "operations.sqlite"
        sentinel.write_bytes(b"sentinel")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--output", str(output)]), 2)
            self.assertEqual(main(["--seed", "-1", "--output", str(self.root / "invalid")]), 2)
        self.assertEqual(sentinel.read_bytes(), b"sentinel")

    def test_evaluation_seeds_are_disjoint_and_manifest_records_budget(self) -> None:
        development = run_batch(fresh_output(self.root / "development"), seed=17, seeds=2, events=1)
        evaluation = run_batch(fresh_output(self.root / "evaluation"), seed=17, seeds=2, events=1, split="evaluation")
        self.assertFalse(set(cast(list[int], development["seeds"])) & set(cast(list[int], evaluation["seeds"])))
        self.assertEqual(development["N"], 2)
        self.assertEqual(development["events_executed"], 2)
        self.assertIn("duration_seconds", development)
        self.assertTrue(development["simulation"])
        self.assertTrue(development["ok"])


if __name__ == "__main__":
    unittest.main()
