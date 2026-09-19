"""Contabilidad sin duplicados ni duraciones humanas presentadas como mediciones."""
import copy
import unittest
from motor.server.coordinacion import summarize


class CoordinationTests(unittest.TestCase):
    def test_peak_end_exclusive_and_full_history(self):
        calls = [{"action_id": f"a{i}", "t": i // 3, "t_end": i // 3 + 1,
                  "channel": "voice", "real": False} for i in range(17)]
        original = copy.deepcopy(calls)
        result = summarize(calls + [calls[0]], [], 6)
        self.assertEqual((result["calls"], result["peak_simultaneous"], result["serial_minutes"]), (17, 3, 51))
        self.assertEqual(result["elapsed_minutes"], 6)
        self.assertEqual(result["N"], 17)
        self.assertEqual(calls, original)

    def test_messages_reports_and_real_split(self):
        calls = [{"action_id": "a", "t": 1, "t_end": 3, "channel": "voice", "real": True},
                 {"action_id": "b", "t": 2, "t_end": 2, "channel": "sms", "real": False}]
        reports = [{"id": "r", "t": 2, "channel": "sms"}, {"id": "r", "t": 2, "channel": "sms"},
                   {"id": "sensor", "t": 2, "channel": "sensor"}]
        result = summarize(calls, reports, 4, call_minutes=4, message_minutes=1, report_minutes=2)
        self.assertEqual((result["calls"], result["messages"], result["reports"]), (1, 1, 1))
        self.assertEqual(result["serial_minutes"], 7)
        self.assertEqual(result["peak_simultaneous"], 2)  # avisos instantáneos no inventan duración
        self.assertEqual(result["real_outbound"], 1)
        self.assertIn("sin verificar", result["assumption"])

    def test_empty_and_invalid_assumptions(self):
        self.assertEqual(summarize([], [], 0)["serial_minutes"], 0)
        for value in (-1, float("nan"), float("inf"), True, "tres"):
            with self.assertRaises(ValueError):
                summarize([], [], 1, call_minutes=value)
