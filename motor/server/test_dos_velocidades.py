"""Dos velocidades: decisión rápida + revisión del enjambre.

    uv run --project motor/server python -m unittest motor.server.test_dos_velocidades -v
"""
from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from motor.contracts import IncidentStatus
from motor.server.app import create_app

SECRET = "secreto-de-prueba-velocidades"
PAPELES = ("triaje", "prioridad", "recursos", "avisos", "vigia", "critico")


def _app(**env):
    base = {"HR_SECRET": SECRET, "TELEGRAM_MODE": "off"}
    base.update(env)
    ctx = patch.dict(os.environ, base, clear=False)
    ctx.start()
    app = create_app("demo-gates", threaded=False, secret=SECRET)
    return app, ctx


class DosVelocidadesTest(unittest.TestCase):
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

    def card(self, iid: str) -> dict:
        st = self.s.state()
        self.assertIn(iid, st["agentes"], st["agentes"].keys())
        return st["agentes"][iid]

    def _rapida(self, **extra):
        aviso_at = extra.pop("aviso_at", time.time() - 9)
        body = {
            "fase": "rapida", "agente": "rapido", "aviso_at": aviso_at,
            "incident_id": "nuevo", "prioridad": 6, "zona": "front_pit",
            "tipo": "crowd", "texto": "Mareo en el foso",
            "porque": "Mareo en el foso: mando médico ya.",
            "recursos": ["med_1"],
            "por_papel": {
                "triaje": "Aviso nuevo, no es duplicado.",
                "prioridad": "Prioridad 6: mareo, no vital.",
                "recursos": "Mandar med_1 al foso.",
                "avisos": "Avisar al sanitario de pista.",
                "vigia": "Vigilar si pierde el conocimiento.",
                "critico": "APROBAR el despacho médico.",
            },
        }
        body.update(extra)
        r = self.post("/hr/tools/decidir", body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json(), aviso_at

    def test_rapida_ejecuta_y_queda_con_latencia(self) -> None:
        d, aviso_at = self._rapida()
        self.assertTrue(d["ok"], d)
        self.assertTrue(any(x.get("recurso") == "med_1" for x in d.get("aceptadas") or []), d)
        iid = d["incident_id"]
        card = self.card(iid)
        vel = card["velocidad"]
        self.assertAlmostEqual(vel["rapida_s"], time.time() - aviso_at, delta=2)
        self.assertGreaterEqual(vel["rapida_s"], 8)
        self.assertEqual(vel["revision"], "pendiente")
        self.assertIsNone(vel.get("revision_s"))
        self.assertIn("rapida", card["fases"])
        self.assertAlmostEqual(card["fases"]["rapida"]["s"], vel["rapida_s"], delta=1)
        for papel in PAPELES:
            self.assertIn(papel, card["agentes"], papel)
            self.assertTrue(card["agentes"][papel]["razonamiento"], papel)
        det = self.c.get(f"/api/agentes/{iid}")
        self.assertEqual(det.status_code, 200, det.text)
        self.assertEqual(det.json()["velocidad"]["revision"], "pendiente")

    def test_revision_confirma_no_cambia_nada(self) -> None:
        d, _ = self._rapida()
        iid = d["incident_id"]
        before = self.s.state()
        acts = [a["id"] for a in before["actions"]]
        assigned = list(next(i for i in before["incidents"] if i["id"] == iid)["assigned"])
        prio = next(i for i in before["incidents"] if i["id"] == iid)["priority"]
        planes = [(p["id"], p.get("invalidated_by"), p.get("supersedes")) for p in before["plans"]
                  if p.get("incident") == iid]
        r = self.post("/hr/tools/decidir", {
            "fase": "revision", "incident_id": iid, "veredicto": "confirma",
            "prioridad": 6, "recursos": ["med_1"],
            "porque": "El enjambre confirma el despacho médico.",
        }).json()
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(r.get("revision"), "confirma")
        self.assertFalse(r.get("aceptadas"), r)
        after = self.s.state()
        self.assertEqual([a["id"] for a in after["actions"]], acts)
        inc = next(i for i in after["incidents"] if i["id"] == iid)
        self.assertEqual(list(inc["assigned"]), assigned)
        self.assertEqual(inc["priority"], prio)
        after_planes = [(p["id"], p.get("invalidated_by"), p.get("supersedes")) for p in after["plans"]
                        if p.get("incident") == iid]
        self.assertEqual(after_planes, planes)
        vel = self.card(iid)["velocidad"]
        self.assertEqual(vel["revision"], "confirma")
        self.assertIsNotNone(vel["revision_s"])
        self.assertGreaterEqual(vel["revision_s"], vel["rapida_s"])

    def test_revision_corrige_genera_plan_nuevo(self) -> None:
        d, _ = self._rapida()
        iid = d["incident_id"]
        before_assigned = list(next(i for i in self.s.state()["incidents"] if i["id"] == iid)["assigned"])
        r = self.post("/hr/tools/decidir", {
            "fase": "revision", "agente": "vigia", "incident_id": iid,
            "veredicto": "corrige", "prioridad": 8,
            "recursos": ["med_1", "sec_1"],
            "porque": "Hay aglomeración: falta seguridad junto al médico.",
        }).json()
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(r.get("revision"), "corrige")
        self.assertTrue(any(x.get("recurso") == "sec_1" for x in r.get("aceptadas") or []), r)
        self.assertFalse(any(x.get("recurso") == "med_1" for x in r.get("aceptadas") or []),
                         "no re-despacha lo que ya iba")
        inc = next(i for i in self.s.state()["incidents"] if i["id"] == iid)
        self.assertEqual(inc["priority"], 8)
        self.assertIn("sec_1", inc["assigned"])
        self.assertEqual(inc["assigned"][:len(before_assigned)], before_assigned)
        planes = [p for p in self.s.state()["plans"] if p.get("incident") == iid]
        muertos = [p for p in planes if p.get("invalidated_by")]
        vivos = [p for p in planes if not p.get("invalidated_by")]
        self.assertTrue(muertos, planes)
        self.assertTrue(any(p.get("supersedes") == muertos[-1]["id"] for p in vivos), planes)
        vel = self.card(iid)["velocidad"]
        self.assertEqual(vel["revision"], "corrige")
        cambio = self.card(iid).get("plan_cambio") or {}
        self.assertTrue(cambio.get("nuevo") or cambio.get("objetivo"), cambio)

    def test_revision_corrige_respeta_barandillas(self) -> None:
        d, _ = self._rapida()
        iid = d["incident_id"]
        pit = next(z for z in self.s.state()["zones"] if z["id"] == "front_pit")
        before = pit["state"]
        r = self.post("/hr/tools/decidir", {
            "fase": "revision", "incident_id": iid, "veredicto": "corrige",
            "prioridad": 9,
            "porque": "Densidad extrema: hay que evacuar el foso.",
            "acciones": [{"kind": "evacuate", "zone": "front_pit"}],
            "requiere_persona": True,
        }).json()
        self.assertTrue(any(a.get("tarjeta") and a.get("kind") == "evacuate" for a in r["aceptadas"]), r)
        after = next(z for z in self.s.state()["zones"] if z["id"] == "front_pit")
        self.assertEqual(after["state"], before, "evacuar no se ejecuta sola")
        self.assertTrue(self.s.state()["approvals"])

    def test_revision_tardia_no_ejecuta(self) -> None:
        d, _ = self._rapida(recursos=["med_2"])
        iid = d["incident_id"]
        inc = self.s.agent.incidents[iid]
        self.s.agent._close(inc, IncidentStatus.RESOLVED, "cerrado en test")
        with self.s.lock:
            self.s._rebuild()
        acts_before = [a["id"] for a in self.s.state()["actions"]]
        r = self.post("/hr/tools/decidir", {
            "fase": "revision", "incident_id": iid, "veredicto": "corrige",
            "prioridad": 9, "recursos": ["sec_2"],
            "porque": "Llega tarde: el incidente ya está cerrado.",
        }).json()
        self.assertTrue(r.get("ok"), r)
        self.assertTrue(r.get("tardia"), r)
        self.assertFalse(r.get("aceptadas"), r)
        self.assertEqual([a["id"] for a in self.s.state()["actions"]], acts_before)
        self.assertEqual(self.card(iid)["velocidad"]["revision"], "corrige")
        self.assertTrue(self.card(iid)["fases"]["revision"].get("tardia"))

        d2, _ = self._rapida(zona="gate_b", texto="Cola en B", porque="Cola en B: mando seguridad.",
                             recursos=["sec_2"], por_papel={
                                 "triaje": "Aviso en B.", "prioridad": "6", "recursos": "sec_2",
                                 "avisos": "—", "vigia": "—", "critico": "ok",
                             })
        iid2 = d2["incident_id"]
        self.post("/hr/tools/decidir", {
            "fase": "revision", "incident_id": iid2, "veredicto": "corrige",
            "prioridad": 7, "recursos": ["sec_2", "sec_3"],
            "porque": "Primera corrección: refuerzo en B.",
        })
        acts2 = [a["id"] for a in self.s.state()["actions"]]
        assigned2 = list(next(i for i in self.s.state()["incidents"] if i["id"] == iid2)["assigned"])
        late = self.post("/hr/tools/decidir", {
            "fase": "revision", "incident_id": iid2, "veredicto": "corrige",
            "prioridad": 9, "recursos": ["sec_2", "vol_1"],
            "porque": "Segunda corrección: ya se había corregido.",
        }).json()
        self.assertTrue(late.get("tardia"), late)
        self.assertFalse(late.get("aceptadas"), late)
        self.assertEqual([a["id"] for a in self.s.state()["actions"]], acts2)
        self.assertEqual(list(next(i for i in self.s.state()["incidents"] if i["id"] == iid2)["assigned"]),
                         assigned2)

    def test_desglose_por_papel(self) -> None:
        d, _ = self._rapida()
        card = self.card(d["incident_id"])
        self.assertEqual(set(PAPELES), set(card["agentes"]) & set(PAPELES))
        self.assertIn("duplicado", card["agentes"]["triaje"]["razonamiento"])
        self.assertIn("med_1", card["agentes"]["recursos"]["razonamiento"])

    def test_desglose_campos_sueltos(self) -> None:
        r = self.post("/hr/tools/decidir", {
            "fase": "rapida", "agente": "rapido", "aviso_at": time.time() - 4,
            "incident_id": "nuevo", "zona": "gate_b", "prioridad": 5,
            "porque": "Cola molesta en B.",
            "triaje": "No hay duplicado en B.",
            "avisos": "Informar al jefe de puerta.",
            "especialistas": [
                {"agente": "prioridad", "razonamiento": "Prioridad 5: incomodidad, no aplastamiento."},
                {"papel": "recursos", "porque": "Aún no hace falta despacho."},
                {"agente": "vigia", "texto": "Si la densidad pasa de 4, corregir."},
                {"agente": "critico", "razonamiento": "APROBAR con seguimiento."},
            ],
        }).json()
        self.assertTrue(r["ok"], r)
        card = self.card(r["incident_id"])
        for papel in PAPELES:
            self.assertIn(papel, card["agentes"], papel)
            self.assertTrue(card["agentes"][papel]["razonamiento"], papel)
        self.assertIn("duplicado", card["agentes"]["triaje"]["razonamiento"])
        self.assertIn("incomodidad", card["agentes"]["prioridad"]["razonamiento"])
        self.assertIn("despacho", card["agentes"]["recursos"]["razonamiento"])
        self.assertIn("puerta", card["agentes"]["avisos"]["razonamiento"])
        self.assertIn("densidad", card["agentes"]["vigia"]["razonamiento"])
        self.assertIn("APROBAR", card["agentes"]["critico"]["razonamiento"])


if __name__ == "__main__":
    unittest.main()
