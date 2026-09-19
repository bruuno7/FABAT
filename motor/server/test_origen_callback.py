"""La fuente del transporte autenticado no convierte al widget en personal."""
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from motor.server.app import create_app


class OrigenCallbackTest(unittest.TestCase):
    def test_widget_cannot_claim_staff_source_in_any_supported_shape(self):
        shapes = ({"source": "med_1"}, {"extracted": {"source": "med_1"}},
                  {"report": {"source": "med_1"}})
        with patch.dict(os.environ, {"TELEGRAM_MODE": "off", "MANDO_CONTACTS": "/dev/null",
                                     "HR_CHAT_TOKEN": "widget-ficticio"}, clear=True):
            app = create_app(threaded=False, secret="backend-ficticio", local_params=False)
            self.addCleanup(app.state.session.close)
            self.addCleanup(app.state.chat.stop)
            with TestClient(app) as client:
                for index, shape in enumerate(shapes):
                    with self.subTest(shape=shape):
                        payload = {"type": "public_report", "event_id": f"widget-origen-{index}",
                                   "text": "Persona mareada en puerta B", "channel": "web", **shape}
                        response = client.post("/hr/events", json=payload,
                                               headers={"X-Mando-Token": "widget-ficticio"})
                        self.assertEqual(response.status_code, 200, response.text)
                        report = next(r for r in app.state.session.world.reports
                                      if r.id == response.json()["report_id"])
                        self.assertEqual(report.source, "asistente")
                        self.assertEqual(str(report.channel), "whatsapp")
                        self.assertEqual(app.state.session._report_meta[report.id]["via"], "web")


if __name__ == "__main__":
    unittest.main()
