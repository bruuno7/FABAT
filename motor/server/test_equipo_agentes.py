"""Equipo de agentes: votos parciales, conflictos, cambio, estado público y cerebro local."""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from motor.server.app import create_app

SECRET = "secreto-de-prueba-equipo"


def _app(**env):
    base = {"HR_SECRET": SECRET, "TELEGRAM_MODE": "off"}
    base.update(env)
    ctx = patch.dict(os.environ, base, clear=False)
    ctx.start()
    app = create_app("demo-gates", threaded=False, secret=SECRET)
    return app, ctx


class EquipoAgentesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.app, self._env = _app()
        self.addCleanup(self._env.stop)
        self.c = TestClient(self.app)
        self.s = self.app.state.session
        self.addCleanup(self.s.close)
        self.addCleanup(self.app.state.chat.stop)
        self.h = {"X-Mando-Token": SECRET}

    def post(self, path: str, body: dict | None = None):
        return self.c.post(path, json=body or {}, headers=self.h)

    def test_parciales_se_componen_y_barandilla_va_a_la_conjunta(self) -> None:
        a = self.post("/hr/tools/decidir", {
            "agente": "triaje", "incident_id": "nuevo", "zona": "front_pit",
            "tipo": "crowd", "texto": "Foso saturado",
            "porque": "Aviso nuevo en el foso, no hay duplicado.",
        }).json()
        self.assertTrue(a["ok"], a)
        iid = a["incident_id"]
        self.post("/hr/tools/decidir", {
            "agente": "prioridad", "incident_id": iid,
            "prioridad": 8, "porque": "Densidad alta y subiendo.",
            "confianza": 0.7, "supuestos": ["La gente sigue entrando"],
        })
        r = self.post("/hr/tools/decidir", {
            "agente": "recursos", "incident_id": iid,
            "prioridad": 8, "porque": "Mandar médico al foso.",
            "recursos": ["med_1"],
        }).json()
        self.assertTrue(any(x.get("recurso") == "med_1" for x in r.get("aceptadas") or []), r)
        st = self.s.state()
        self.assertIn("agentes", st)
        card = st["agentes"][iid]
        self.assertIn("triaje", card["agentes"])
        self.assertIn("prioridad", card["agentes"])
        self.assertIn("recursos", card["agentes"])
        self.assertTrue(card["agentes"]["triaje"]["razonamiento"])
        self.assertTrue(card["ejecutado"])
        det = self.c.get(f"/api/agentes/{iid}")
        self.assertEqual(det.status_code, 200, det.text)
        self.assertEqual(det.json()["incident_id"], iid)

    def test_conflicto_no_ejecuta(self) -> None:
        a = self.post("/hr/tools/decidir", {
            "agente": "prioridad", "incident_id": "nuevo", "zona": "gate_b",
            "prioridad": 4, "porque": "Cola molesta, no urgente.",
        }).json()
        iid = a["incident_id"]
        before = [x["id"] for x in self.s.state()["actions"]]
        b = self.post("/hr/tools/decidir", {
            "agente": "critico", "incident_id": iid,
            "prioridad": 9, "porque": "Riesgo de aplastamiento.",
            "recursos": ["med_1"],
        }).json()
        self.assertFalse(b.get("ok"), b)
        self.assertTrue(b.get("conflicto"), b)
        after = [x["id"] for x in self.s.state()["actions"]]
        self.assertEqual(before, after)
        self.assertFalse(any(x.get("recurso") == "med_1" for x in b.get("aceptadas") or []))

    def test_evacuar_en_conjunta_sigue_siendo_tarjeta(self) -> None:
        pit = next(z for z in self.s.state()["zones"] if z["id"] == "front_pit")
        before = pit["state"]
        r = self.post("/hr/tools/decidir", {
            "agente": "critico", "incident_id": "nuevo", "zona": "front_pit",
            "prioridad": 9, "porque": "Hay que evacuar el foso.",
            "acciones": [{"kind": "evacuate", "zone": "front_pit"}],
            "requiere_persona": True,
        }).json()
        self.assertTrue(any(a.get("tarjeta") for a in r["aceptadas"]), r)
        after = next(z for z in self.s.state()["zones"] if z["id"] == "front_pit")
        self.assertEqual(after["state"], before)

    def test_cambio_devuelve_afectados(self) -> None:
        d = self.post("/hr/tools/decidir", {
            "incident_id": "nuevo", "zona": "gate_b", "prioridad": 6,
            "porque": "Mandar M1 a la puerta B.",
            "recursos": ["med_1"],
        }).json()
        iid = d["incident_id"]
        r = self.post("/hr/tools/cambio", {
            "tipo": "rechazo", "incident_id": iid, "recurso": "med_1",
        }).json()
        self.assertTrue(r["ok"], r)
        self.assertTrue(any(x["incident_id"] == iid for x in r["afectados"]), r)
        self.assertIn("planes", r["afectados"][0])

    def test_memoria_guardar_por_agente(self) -> None:
        g = self.post("/hr/tools/memoria/guardar", {
            "id": "ce-prio-1", "agente": "prioridad", "tipo": "crowd", "zona": "gate_b",
            "razonamiento": "prioridad 7 porque B satura",
            "decision": {"prioridad": 7}, "confianza": 0.6,
            "supuestos": ["No cierra la puerta"],
            "resultado": {"texto": "voto de prioridad"},
        }).json()
        self.assertTrue(g["ok"], g)
        hit = self.post("/hr/tools/memoria/buscar", {"tipo": "crowd", "zona": "gate_b"}).json()
        row = next(c for c in hit["casos"] if c["id"] == "ce-prio-1")
        self.assertEqual(row["agente"], "prioridad")

    def test_cerebro_local_equipo_fake(self) -> None:
        from motor.server.cerebro_llm import cycle, fake_team
        votes = fake_team({"incidentes": [], "recursos_libres": {}})
        for name in ("triaje", "prioridad", "recursos", "avisos", "vigia", "critico"):
            self.assertIn(name, votes)
        out = cycle(self.s, {"texto": "equipo test", "zona": "front_pit"}, fake=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["fake"])
        self.assertIn("votos", out)
        blob = json.dumps(self.s.state())
        self.assertNotIn(SECRET, blob)
        self.assertNotIn("chat_id", blob)


if __name__ == "__main__":
    unittest.main()
