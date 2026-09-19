"""Herramientas /hr/tools del cerebro, barandillas, memoria y modo MANDO_CEREBRO."""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from motor.server.app import create_app

SECRET = "secreto-de-prueba-cerebro"


def _app(case="demo-gates", **env):
    base = {"MANDO_CEREBRO": "", "HR_SECRET": SECRET}
    base.update(env)
    ctx = patch.dict(os.environ, base, clear=False)
    ctx.start()
    if not base.get("MANDO_CEREBRO"):
        os.environ.pop("MANDO_CEREBRO", None)
    app = create_app(case, threaded=False, secret=SECRET)
    return app, ctx


class CerebroToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.app, self._env = _app()
        self.addCleanup(self._env.stop)
        self.c = TestClient(self.app)
        self.s = self.app.state.session
        self.addCleanup(self.s.close)
        self.addCleanup(self.app.state.chat.stop)
        self.h = {"X-Mando-Token": SECRET}

    def post(self, path: str, body: dict | None = None, headers: dict | None = None):
        return self.c.post(path, json=body or {}, headers=headers if headers is not None else self.h)

    def test_sin_token_401(self) -> None:
        self.assertEqual(self.post("/hr/tools/contexto", {}, headers={}).status_code, 401)
        self.assertEqual(self.post("/hr/tools/contexto", {}, headers={"X-Mando-Token": "malo"}).status_code, 401)

    def test_contexto(self) -> None:
        r = self.post("/hr/tools/contexto", {"tipo": "crowd", "zona": "gate_b", "texto": "aviso estructurado"})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        for k in ("incidentes", "recursos_libres", "recursos_ocupados", "zonas", "previsiones",
                  "decisiones_pendientes", "memoria", "texto"):
            self.assertIn(k, d)
        self.assertIn("lecciones_aprobadas", d["memoria"])
        self.assertIn("casos_parecidos", d["memoria"])
        self.assertEqual(d["cerebro"], "reglas")
        blob = json.dumps(d)
        self.assertNotIn(SECRET, blob)
        self.assertNotIn("chat_id", blob)
        self.assertNotIn("+34", blob)

    def test_ensayar(self) -> None:
        r = self.post("/hr/tools/ensayar", {
            "opciones": ["desviar puerta B → A y C", "mandar M2 al foso"],
            "minutos": 12,
        })
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(len(d["opciones"]), 2)
        self.assertEqual(d["opciones"][0]["kind"], "reroute")
        self.assertTrue(d["opciones"][0]["numeros"])
        self.assertEqual(d["opciones"][1]["kind"], "dispatch")
        self.assertEqual(d["opciones"][1]["resource"], "med_2")
        self.assertIn("supuestos", d)

    def test_decidir_vital_aunque_no_pida_despacho(self) -> None:
        r = self.post("/hr/tools/decidir", {
            "incident_id": "nuevo", "prioridad": 9, "zona": "front_pit",
            "porque": "Persona en el suelo que no responde y no respira.",
            "recursos": [],
        })
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertTrue(any(a.get("kind") == "dispatch" and a.get("ok") for a in d["aceptadas"]), d)
        self.assertTrue(any(a.get("origen") == "barandilla" for a in d["aceptadas"]), d)

    def test_evacuar_es_tarjeta(self) -> None:
        pit = next(z for z in self.s.state()["zones"] if z["id"] == "front_pit")
        before = pit["state"]
        r = self.post("/hr/tools/decidir", {
            "incident_id": "nuevo", "prioridad": 9, "zona": "front_pit",
            "porque": "Densidad extrema: hay que evacuar el foso.",
            "acciones": [{"kind": "evacuate", "zone": "front_pit"}],
            "recursos": [], "requiere_persona": True,
            "confianza": 0.7, "supuestos": ["La gente obedece megafonía"], "vigilar": ["densidad foso"],
        })
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertTrue(any(a.get("tarjeta") and a.get("kind") == "evacuate" for a in d["aceptadas"]), d)
        self.assertFalse(any(a.get("kind") == "evacuate" and not a.get("tarjeta") for a in d["aceptadas"]))
        after = next(z for z in self.s.state()["zones"] if z["id"] == "front_pit")
        self.assertEqual(after["state"], before, "evacuar no se ejecuta sola")
        self.assertTrue(self.s.state()["approvals"])
        exp = self.c.get("/api/explica").json()
        self.assertEqual(exp["origen"], "agente HR")

    def test_destino_fuera_de_lista(self) -> None:
        r = self.post("/hr/tools/decidir", {
            "incident_id": "nuevo", "prioridad": 4,
            "porque": "Mandar un médico a una zona que no existe.",
            "recursos": [{"id": "med_1", "zona": "marte"}],
        })
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertTrue(any("lista blanca" in (b.get("motivo") or "") for b in d["bloqueadas"]), d)
        self.assertFalse(any(a.get("kind") == "dispatch" and a.get("ok") for a in d["aceptadas"]))

    def test_recurso_inexistente_u_ocupado(self) -> None:
        a = self.post("/hr/tools/decidir", {
            "incident_id": "nuevo", "prioridad": 6, "zona": "front_pit",
            "porque": "Mandar M1 al foso por un mareo.",
            "recursos": ["med_1"],
        }).json()
        self.assertTrue(any(x.get("recurso") == "med_1" for x in a["aceptadas"]), a)
        iid = a["incident_id"]
        b = self.post("/hr/tools/decidir", {
            "incident_id": iid, "prioridad": 6,
            "porque": "El mismo equipo otra vez.",
            "recursos": ["med_1"],
        }).json()
        self.assertTrue(any("ocupado" in (x.get("motivo") or "") for x in b["bloqueadas"]), b)
        ghost = self.post("/hr/tools/decidir", {
            "incident_id": iid, "prioridad": 5,
            "porque": "Un recurso que no existe.",
            "recursos": ["med_99"],
        }).json()
        self.assertTrue(any("inexistente" in (x.get("motivo") or "") for x in ghost["bloqueadas"]), ghost)

    def test_memoria_guarda_y_busca(self) -> None:
        g = self.post("/hr/tools/memoria/guardar", {
            "id": "ce-test-busca", "tipo": "crowd", "zona": "gate_b", "franja": "20:00",
            "razonamiento": "desvío a A porque B saturaba",
            "decision": {"porque": "desvío a A", "prioridad": 6},
            "acciones": [{"kind": "reroute"}],
            "resultado": {"texto": "pico bajó a 3,8"},
        }).json()
        self.assertTrue(g["ok"], g)
        hit = self.post("/hr/tools/memoria/buscar", {"tipo": "crowd", "zona": "gate_b"}).json()
        self.assertTrue(any(c["id"] == "ce-test-busca" for c in hit["casos"]), hit)
        txt = self.post("/hr/tools/memoria/buscar", {"texto": "saturaba"}).json()
        self.assertTrue(any(c["id"] == "ce-test-busca" for c in txt["casos"]), txt)

    def test_leccion_no_aprobada_no_sale_en_contexto(self) -> None:
        self.post("/hr/tools/memoria/guardar", {
            "id": "ce-test-leccion", "tipo": "crowd", "zona": "gate_b",
            "resultado": {"texto": "evidencia N=3"},
        })
        prop = self.post("/hr/tools/memoria/lecciones", {
            "accion": "proponer", "id": "L-test-noaprobar",
            "texto": "Nunca desviar B hacia C si C ya va a 4/m²",
            "evidencia": {"ids": ["ce-test-leccion"], "n": 3},
            "tipo": "crowd", "zona": "gate_b",
        }).json()
        self.assertEqual(prop["estado"], "propuesta", prop)
        ctx = self.post("/hr/tools/contexto", {"tipo": "crowd", "zona": "gate_b"}).json()
        ids = [x["id"] for x in ctx["memoria"]["lecciones_aprobadas"]]
        self.assertNotIn("L-test-noaprobar", ids)
        ok = self.post("/api/memoria/lecciones", {"id": "L-test-noaprobar", "accion": "aprobar", "by": "test"}).json()
        self.assertEqual(ok["estado"], "aprobada", ok)
        ctx2 = self.post("/hr/tools/contexto", {"tipo": "crowd", "zona": "gate_b"}).json()
        ids2 = [x["id"] for x in ctx2["memoria"]["lecciones_aprobadas"]]
        self.assertIn("L-test-noaprobar", ids2)

    def test_nada_reservado_ni_secretos(self) -> None:
        d = self.post("/hr/tools/decidir", {
            "incident_id": "nuevo", "prioridad": 8, "zona": "toilets",
            "porque": "Agresión sexual en los aseos, la han tocado y no la dejan irse.",
            "recursos": [],
        }).json()
        self.assertTrue(d["ok"], d)
        ctx = self.post("/hr/tools/contexto", {"tipo": "aggression", "zona": "toilets",
                                              "texto": "chat_id 999 y +34600111222"}).json()  # revisor: ok teléfono inventado
        blob = json.dumps(ctx, ensure_ascii=False).lower()
        self.assertNotIn("sexual", blob)
        self.assertNotIn("tocado", blob)
        self.assertNotIn("chat_id", blob)
        self.assertNotIn("600111222", blob.replace(" ", ""))
        self.assertNotIn(SECRET.lower(), blob)
        st = json.dumps(self.s.state(), ensure_ascii=False).lower()
        self.assertNotIn("la han tocado", st)
        self.assertTrue(
            any("reservad" in str(i.get("que") or i.get("label") or "").lower()
                or i.get("type") == "reserved"
                for i in (ctx["incidentes"] + self.s.state()["incidents"])),
            ctx["incidentes"])

    def test_sin_mando_cerebro_igual_que_antes(self) -> None:
        self.assertEqual(self.s.state()["session"]["cerebro"], "reglas")
        for _ in range(12):
            self.s.tick()
        st = self.s.state()
        self.assertTrue(st["incidents"], "Mando debería tener ya el incidente de la Puerta B")
        self.assertTrue(st["plans"], "el planificador de reglas sigue decidiendo")

    def test_payload_json_happyrobot(self) -> None:
        r = self.post("/hr/tools/contexto", {"payload_json": json.dumps({"tipo": "crowd", "zona": "gate_b"})})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["aviso"]["zona"], "gate_b")


class CerebroBarandillasTest(unittest.TestCase):
    def tearDown(self) -> None:
        if getattr(self, "s", None):
            self.s.close()
        if getattr(self, "app", None):
            self.app.state.chat.stop()
        if getattr(self, "_env", None):
            self._env.stop()

    def test_vital_despacha_aunque_el_agente_calle(self) -> None:
        self.app, self._env = _app(MANDO_CEREBRO="agente", MANDO_CEREBRO_TIMEOUT_S="30")
        self.s = self.app.state.session
        self.s.report("voice", "Hay una persona en el suelo que no responde y no respira bien, ¡ayuda!",
                      zone="front_pit")
        self.s.tick()
        self.s.tick()
        assigned = [r for r in self.s.state()["resources"]
                    if r["id"].startswith("med") and r.get("status") != "available"]
        incs = [i for i in self.s.state()["incidents"] if i.get("life_threat") or (i.get("priority") or 0) >= 8]
        self.assertTrue(assigned or any(i.get("assigned") for i in incs),
                        {"res": self.s.state()["resources"], "inc": self.s.state()["incidents"]})

    def test_timeout_plan_b_de_reglas(self) -> None:
        self.app, self._env = _app(MANDO_CEREBRO="agente", MANDO_CEREBRO_TIMEOUT_S="8")
        self.s = self.app.state.session
        self.s.report("voice", "Hay una pelea entre varios tíos, se están pegando fuerte", zone="gate_c")
        self.s.tick()
        self.assertFalse(any((a.get("origen") or "") == "plan B reglas" for a in self.s.state()["actions"]))
        os.environ["MANDO_CEREBRO_TIMEOUT_S"] = "0"
        self.s.tick()
        st = self.s.state()
        self.assertTrue(any((a.get("origen") or "") == "plan B reglas" for a in st["actions"])
                        or st["plans"]
                        or any(e.get("kind") == "cerebro" for e in st["log"]),
                        st["log"][-8:])


class CerebroLlmTest(unittest.TestCase):
    def test_fake_y_reintento_json(self) -> None:
        from motor.server.cerebro_llm import parse_decision_json, razonar, fake_brain
        d = fake_brain({"incidentes": [], "recursos_libres": {}})
        self.assertIn("porque", d)
        n = {"i": 0}

        def client(_prompt: str) -> str:
            n["i"] += 1
            if n["i"] == 1:
                return "esto no es json"
            return json.dumps(d)

        out = razonar({"incidentes": []}, client=client, fake=False)
        self.assertEqual(n["i"], 2)
        self.assertEqual(out["porque"], d["porque"])
        wrapped = parse_decision_json("```json\n" + json.dumps({"decision": d}) + "\n```")
        self.assertEqual(wrapped["porque"], d["porque"])

    def test_ciclo_local_fake(self) -> None:
        from motor.server.cerebro_llm import cycle
        from motor.server.app import Session, load_case
        s = Session(load_case("demo-1"), threaded=False, playbook="seed", local_params=False)
        self.addCleanup(s.close)
        out = cycle(s, {"texto": "ciclo test", "zona": "front_pit"}, fake=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["fake"])
        self.assertTrue(out["episodio"]["ok"] or out["episodio"].get("id"))


if __name__ == "__main__":
    unittest.main()
