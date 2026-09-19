"""Enjambre: pizarra, objeciones, confianza, lecciones por agente, herramientas y adaptación."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from motor.server.app import create_app

SECRET = "secreto-de-prueba-enjambre"


def _app(case="demo-gates", **env):
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    base = {
        "HR_SECRET": SECRET, "TELEGRAM_MODE": "off", "MANDO_CEREBRO": "",
        "MANDO_PUBLIC_URL": "", "MANDO_DB": tmp.name, "MANDO_LLM": "0",
    }
    base.update(env)
    ctx = patch.dict(os.environ, base, clear=False)
    ctx.start()
    if not base.get("MANDO_CEREBRO"):
        os.environ.pop("MANDO_CEREBRO", None)
    app = create_app(case, threaded=False, secret=SECRET)
    return app, ctx, tmp.name


class EnjambreTest(unittest.TestCase):
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

    def _incidente(self, **kw) -> str:
        body = {"incident_id": "nuevo", "prioridad": 6, "zona": "front_pit",
                "porque": "Aviso de demo para el enjambre.", "recursos": []}
        body.update(kw)
        d = self.post("/hr/tools/decidir", body).json()
        self.assertTrue(d.get("ok") or d.get("incident_id"), d)
        return d["incident_id"]

    def test_pizarra_publicar_y_leer(self) -> None:
        iid = self._incidente()
        a = self.post("/hr/tools/pizarra/publicar", {
            "de": "prioridad", "para": "recursos", "incidente": iid, "tipo": "propuesta",
            "texto": "Prioridad 7: el foso sube.", "confianza": 0.6,
        }).json()
        self.assertTrue(a["ok"], a)
        pid = a["id"]
        self.post("/hr/tools/pizarra/publicar", {
            "de": "recursos", "para": "prioridad", "incidente": iid, "tipo": "revision",
            "enlaza": pid, "texto": "De acuerdo, hay médico libre.", "gravedad": "baja",
        })
        self.post("/hr/tools/pizarra/publicar", {
            "de": "avisos", "para": "todos", "incidente": iid, "tipo": "observacion",
            "texto": "Nadie más avisado.",
        })
        leer = self.post("/hr/tools/pizarra/leer", {"agente": "prioridad", "incidente": iid, "n": 10}).json()
        self.assertTrue(leer["ok"], leer)
        dests = [m["para"] for m in leer["mensajes"]]
        self.assertIn("prioridad", dests)
        self.assertLessEqual(dests.index("prioridad"), dests.index("todos") if "todos" in dests else 99)

    def test_objecion_alta_bloquea_y_escala(self) -> None:
        iid = self._incidente()
        prop = self.post("/hr/tools/pizarra/publicar", {
            "de": "recursos", "para": "todos", "incidente": iid, "tipo": "propuesta",
            "texto": "Mandar med_1 al foso.",
        }).json()
        self.post("/hr/tools/pizarra/publicar", {
            "de": "critico", "para": "recursos", "incidente": iid, "tipo": "objecion",
            "enlaza": prop["id"], "texto": "Ese médico cubre la otra cola.", "gravedad": "alta",
        })
        r = self.post("/hr/tools/decidir", {
            "agente": "equipo", "incident_id": iid, "prioridad": 6,
            "porque": "Ejecutar el despacho pese a la objeción.", "recursos": ["med_1"],
        }).json()
        self.assertFalse(r.get("ok"), r)
        self.assertTrue(r.get("resolver_primero"), r)
        self.assertTrue(r.get("objeciones"), r)
        self.assertFalse(any(a.get("recurso") == "med_1" for a in r.get("aceptadas") or []))

        self.post("/hr/tools/pizarra/publicar", {
            "de": "critico", "para": "recursos", "incidente": iid, "tipo": "objecion",
            "enlaza": prop["id"], "texto": "Sigue sin resolver.", "gravedad": "alta",
            "_ts": 1.0,
        })
        r2 = self.post("/hr/tools/decidir", {
            "agente": "equipo", "incident_id": iid, "prioridad": 6,
            "porque": "Reintentar tras el plazo.", "recursos": ["med_1"],
        }).json()
        self.assertTrue(r2.get("escalada") or r2.get("requiere_persona") or self.s.state()["approvals"], r2)

    def test_vital_no_espera_objecion(self) -> None:
        d = self.post("/hr/tools/decidir", {
            "incident_id": "nuevo", "prioridad": 9, "zona": "front_pit",
            "porque": "Persona en el suelo que no responde y no respira.",
            "recursos": [],
        }).json()
        iid = d["incident_id"]
        prop = self.post("/hr/tools/pizarra/publicar", {
            "de": "prioridad", "para": "todos", "incidente": iid, "tipo": "propuesta",
            "texto": "Esperar más datos.",
        }).json()
        self.post("/hr/tools/pizarra/publicar", {
            "de": "critico", "para": "prioridad", "incidente": iid, "tipo": "objecion",
            "enlaza": prop["id"], "texto": "No despachar aún.", "gravedad": "alta",
        })
        r = self.post("/hr/tools/decidir", {
            "agente": "equipo", "incident_id": iid, "prioridad": 9,
            "porque": "Sigue sin responder ni respirar: despacho.",
            "recursos": [],
        }).json()
        self.assertTrue(any(a.get("kind") == "dispatch" and a.get("ok") for a in r.get("aceptadas") or []), r)

    def test_confianza_sube_baja_y_sin_evidencia(self) -> None:
        a = self.post("/hr/tools/resultado", {
            "agente": "recursos", "familia": "crowd", "resultado": "aceptó",
        }).json()
        self.assertEqual(a["n"], 1)
        self.assertTrue(a["sin_evidencia"], a)
        self.assertEqual(a["etiqueta"], "sin evidencia")
        self.post("/hr/tools/resultado", {"agente": "recursos", "familia": "crowd", "resultado": "aceptó"})
        b = self.post("/hr/tools/resultado", {"agente": "recursos", "familia": "crowd", "resultado": "aceptó"}).json()
        self.assertGreaterEqual(b["n"], 3)
        self.assertFalse(b["sin_evidencia"], b)
        self.assertEqual(b["tendencia"], "sube")
        hi = b["puntuacion"]
        c = self.post("/hr/tools/resultado", {
            "agente": "recursos", "familia": "crowd", "resultado": "rechazó",
        }).json()
        self.assertLess(c["puntuacion"], hi)
        self.assertEqual(c["tendencia"], "baja")
        ctx = self.post("/hr/tools/contexto", {"tipo": "crowd", "zona": "gate_b"}).json()
        row = next(x for x in ctx["confianza_agentes"] if x["agente"] == "recursos")
        self.assertGreaterEqual(row["n"], 3)
        exp = self.c.get("/api/explica").json()
        self.assertIn("sin evidencia", exp["enjambre"]["regla_peso"])
        self.assertIn("bayesiana", exp["enjambre"]["regla_peso"])

    def test_lecciones_por_agente_y_revocar(self) -> None:
        self.post("/hr/tools/memoria/guardar", {
            "id": "ce-enj-1", "agente": "recursos", "tipo": "crowd", "zona": "gate_b",
            "resultado": {"texto": "evidencia"},
        })
        prop = self.post("/hr/tools/memoria/lecciones", {
            "accion": "proponer", "id": "L-enj-rec",
            "texto": "En incendios de restauración manda técnico y seguridad a la vez",
            "evidencia": {"ids": ["ce-enj-1"], "n": 3}, "tipo": "crowd",
            "para_agente": "recursos",
        }).json()
        self.assertEqual(prop["estado"], "propuesta", prop)
        self.post("/api/memoria/lecciones", {"id": "L-enj-rec", "accion": "aprobar", "by": "test"})
        ctx_rec = self.post("/hr/tools/contexto", {
            "tipo": "crowd", "zona": "gate_b", "agente": "recursos",
        }).json()
        ids_rec = [x["id"] for x in ctx_rec["memoria"]["lecciones_aprobadas"]]
        self.assertIn("L-enj-rec", ids_rec)
        ctx_av = self.post("/hr/tools/contexto", {
            "tipo": "crowd", "zona": "gate_b", "agente": "avisos",
        }).json()
        ids_av = [x["id"] for x in ctx_av["memoria"]["lecciones_aprobadas"]]
        self.assertNotIn("L-enj-rec", ids_av)
        piz = self.post("/hr/tools/pizarra/leer", {"agente": "recursos"}).json()
        self.assertTrue(any(x["id"] == "L-enj-rec" for x in piz.get("lecciones") or []), piz)
        piz_av = self.post("/hr/tools/pizarra/leer", {"agente": "avisos"}).json()
        self.assertFalse(any(x["id"] == "L-enj-rec" for x in piz_av.get("lecciones") or []))
        rev = self.post("/api/memoria/lecciones", {"id": "L-enj-rec", "accion": "revocar", "by": "test"}).json()
        self.assertEqual(rev["estado"], "revocada", rev)
        ctx2 = self.post("/hr/tools/contexto", {"tipo": "crowd", "agente": "recursos"}).json()
        self.assertNotIn("L-enj-rec", [x["id"] for x in ctx2["memoria"]["lecciones_aprobadas"]])

    def test_s_enjambre_sin_reservado(self) -> None:
        self.post("/hr/tools/decidir", {
            "incident_id": "nuevo", "prioridad": 8, "zona": "toilets",
            "porque": "Agresión sexual en los aseos, la han tocado y no la dejan irse.",
            "recursos": [],
        })
        reserved = next(i for i in self.s.state()["incidents"] if i.get("reserved") or i.get("type") == "reserved")
        self.post("/hr/tools/pizarra/publicar", {
            "de": "triaje", "para": "todos", "incidente": reserved["id"], "tipo": "observacion",
            "texto": "detalle que no debe salir",
        })
        st = self.s.state()
        blob = json.dumps(st.get("enjambre"), ensure_ascii=False).lower()
        self.assertNotIn("sexual", blob)
        self.assertNotIn("tocado", blob)
        self.assertNotIn(SECRET.lower(), blob)
        self.assertIn("agentes", st["enjambre"])
        self.assertIn("mensajes", st["enjambre"])
        self.assertIn("aristas", st["enjambre"])
        self.assertIn("modo", st["enjambre"])

    def test_fake_dos_situaciones_distinto_razonamiento(self) -> None:
        from motor.server.cerebro_llm import fake_team
        crowd = fake_team({
            "aviso": {"tipo": "crowd", "zona": "gate_b", "texto": "Puerta B saturada, densidad alta"},
            "incidentes": [{"id": "M-1", "zona": "gate_b", "vital": False, "prioridad": 5}],
            "recursos_libres": {"medical": [{"id": "med_1", "eta_min": 4}],
                                "security": [{"id": "sec_1", "eta_min": 1}]},
        })
        vital = fake_team({
            "aviso": {"tipo": "medical", "zona": "front_pit",
                      "texto": "Persona en el suelo que no responde y no respira"},
            "incidentes": [{"id": "M-2", "zona": "front_pit", "vital": True, "prioridad": 9}],
            "recursos_libres": {"medical": [{"id": "med_2", "eta_min": 2}]},
        })
        self.assertNotEqual(crowd["prioridad"]["porque"], vital["prioridad"]["porque"])
        self.assertNotEqual(crowd["recursos"]["recursos"], vital["recursos"]["recursos"])
        self.assertNotEqual(crowd["triaje"]["porque"], vital["triaje"]["porque"])

    def test_ciclo_local_publica_pizarra(self) -> None:
        from motor.server.cerebro_llm import cycle
        out = cycle(self.s, {"texto": "ciclo enjambre", "zona": "front_pit"}, fake=True)
        self.assertTrue(out["ok"] or out.get("resultado"), out)
        leer = self.post("/hr/tools/pizarra/leer", {"agente": "critico", "n": 20}).json()
        self.assertTrue(leer["mensajes"], leer)
        self.assertTrue(any(m.get("de") == "critico" for m in leer["mensajes"]), leer["mensajes"])

    def test_herramientas_observar(self) -> None:
        z = self.post("/hr/tools/zona", {"zona": "gate_b"}).json()
        self.assertTrue(z["ok"], z)
        self.assertIn("densidad", z)
        rec = self.post("/hr/tools/recurso", {"recurso": "med_1", "zona": "front_pit"}).json()
        self.assertEqual(rec["id"], "med_1")
        ru = self.post("/hr/tools/rutas", {"de": "gate_a", "a": "front_pit"}).json()
        self.assertTrue(ru["ok"], ru)
        stf = self.post("/hr/tools/staff", {"rol": "medical"}).json()
        self.assertTrue(stf["por_rol"], stf)
        prev = self.post("/hr/tools/previsiones", {}).json()
        self.assertIn("por_minuto", prev)
        par = self.post("/hr/tools/incidentes_parecidos", {"tipo": "crowd"}).json()
        self.assertIn("casos", par)
        proto = self.post("/hr/tools/protocolo", {"tipo": "unresponsive_person"}).json()
        self.assertTrue(proto["ok"], proto)
        self.assertEqual(proto["id"], "unresponsive_person")
        conf = self.post("/hr/tools/confianza", {"familia": "crowd"}).json()
        self.assertTrue(conf["agentes"], conf)

    def test_acciones_posibles_demo_minimo_6(self) -> None:
        app, env = _app("demo-1")
        self.addCleanup(env.stop)
        c = TestClient(app)
        s = app.state.session
        self.addCleanup(s.close)
        self.addCleanup(app.state.chat.stop)
        h = {"X-Mando-Token": SECRET}
        d = c.post("/hr/tools/decidir", json={
            "incident_id": "nuevo", "prioridad": 6, "zona": "front_pit",
            "porque": "Mareo en el foso, simulación demo-1.", "recursos": [],
        }, headers=h).json()
        iid = d["incident_id"]
        r = c.post("/hr/tools/acciones_posibles", json={"incidente": iid}, headers=h).json()
        self.assertGreaterEqual(r["n"], 6, r)
        kinds = {o["kind"] for o in r["opciones"]}
        for k in ("dispatch", "watch", "escalate", "request_external", "evacuate", "stop_show"):
            self.assertIn(k, kinds, r["opciones"])
        graves = [o for o in r["opciones"] if o["kind"] in ("evacuate", "stop_show", "request_external")]
        self.assertTrue(all(o["exige_persona"] for o in graves), graves)
        cmp_ = c.post("/hr/tools/comparar_opciones", json={
            "opciones": [o["texto"] for o in r["opciones"][:5]],
        }, headers=h).json()
        self.assertEqual(cmp_["elige"], "agente")
        self.assertGreaterEqual(len(cmp_["tabla"]), 1)

    def test_ensayar_hasta_5(self) -> None:
        r = self.post("/hr/tools/ensayar", {
            "opciones": ["desviar puerta B → A", "mandar M2 al foso", "vigilar sin actuar"],
            "minutos": 12,
        }).json()
        self.assertEqual(len(r["opciones"]), 3, r)

    def test_modo_cambia_con_senales(self) -> None:
        from motor.server.adaptativo import elegir_modo
        self.assertEqual(elegir_modo({"varios_incidentes": False, "riesgo_vital": False})["id"], "calma")
        self.assertEqual(elegir_modo({"varios_incidentes": True})["id"], "carga")
        self.assertEqual(elegir_modo({"recurso_critico_agotado": True, "riesgo_vital": True})["id"], "crisis")
        a = self.post("/hr/tools/analizar_situacion", {}).json()
        self.assertIn(a["modo"]["id"], ("calma", "carga", "crisis"))
        self._incidente()
        self._incidente(zona="gate_b", porque="Segundo aviso: cola en B.")
        b = self.post("/hr/tools/analizar_situacion", {}).json()
        self.assertIn(b["modo"]["id"], ("carga", "crisis", "calma"))
        self.assertEqual(self.s.state()["enjambre"]["modo"]["id"], b["modo"]["id"])

    def test_autonomia_y_grave_siempre_persona(self) -> None:
        for _ in range(3):
            self.post("/hr/tools/resultado", {
                "agente": "recursos", "familia": "crowd", "resultado": "rechazó",
            })
        auto = self.c.get("/api/adaptacion").json()
        row = next(x for x in auto["autonomia"] if x["agente"] == "recursos")
        self.assertEqual(row["autonomia"], "revision")
        iid = self._incidente(tipo="crowd")
        r = self.post("/hr/tools/decidir", {
            "agente": "recursos", "incident_id": iid, "prioridad": 5,
            "tipo": "crowd", "porque": "Mandar un médico con confianza baja.",
            "recursos": ["med_2"],
        }).json()
        self.assertTrue(r.get("pendiente_revision"), r)
        self.assertFalse(any(a.get("recurso") == "med_2" for a in r.get("aceptadas") or []))
        for _ in range(8):
            self.post("/hr/tools/resultado", {
                "agente": "recursos", "familia": "crowd", "resultado": "aceptó",
            })
        grave = self.post("/hr/tools/decidir", {
            "agente": "recursos", "incident_id": "nuevo", "zona": "front_pit", "prioridad": 9,
            "tipo": "crowd", "porque": "Hay que evacuar el foso aunque la autonomía sea alta.",
            "acciones": [{"kind": "evacuate", "zone": "front_pit"}],
            "requiere_persona": True,
        }).json()
        self.assertTrue(any(a.get("tarjeta") for a in grave.get("aceptadas") or []), grave)

    def test_ritmo_segun_volatilidad(self) -> None:
        from motor.server import adaptativo
        adaptativo.aplicar_modo(self.s, {"id": "calma", "porque": "test"}, {"volatil": False})
        r0 = adaptativo.ritmo_vigia(self.s)
        self.assertEqual(r0["cada_min"], 5)
        adaptativo.aplicar_modo(self.s, {"id": "calma", "porque": "test"}, {"volatil": True})
        r1 = adaptativo.ritmo_vigia(self.s)
        self.assertLess(r1["cada_min"], r0["cada_min"])
        adaptativo.aplicar_modo(self.s, {"id": "crisis", "porque": "test"}, {"volatil": True})
        self.assertEqual(adaptativo.ritmo_vigia(self.s)["cada_min"], 1)

    def test_prompt_no_aprobado_no_se_usa_y_revertir(self) -> None:
        from motor.server.adaptativo import load_prompt
        from motor.server.cerebro_llm import load_agent_prompt
        original = load_agent_prompt("prioridad")
        prop = self.post("/hr/tools/prompt/proponer", {
            "agente": "prioridad", "cuerpo": original + "\n# VERSION NUEVA DE TEST\n",
            "evidencia": {"ids": ["ce-x"], "n": 3}, "id": "PV-test-1",
        }).json()
        self.assertEqual(prop["estado"], "propuesta", prop)
        used = load_prompt(self.s, "prioridad", original)
        self.assertNotIn("VERSION NUEVA DE TEST", used)
        ok = self.c.post("/api/prompt/versiones", json={"accion": "aprobar", "id": "PV-test-1", "by": "test"}).json()
        self.assertTrue(ok.get("activa"), ok)
        used2 = load_prompt(self.s, "prioridad", original)
        self.assertIn("VERSION NUEVA DE TEST", used2)
        back = self.c.post("/api/prompt/versiones", json={"accion": "revertir", "agente": "prioridad", "by": "test"}).json()
        self.assertTrue(back.get("ok"), back)
        used3 = load_prompt(self.s, "prioridad", original)
        self.assertNotIn("VERSION NUEVA DE TEST", used3)
        ad = self.c.get("/api/adaptacion").json()
        self.assertIn("modo", ad)
        self.assertIn("autonomia", ad)
        self.assertIn("ritmo_vigia", ad)


if __name__ == "__main__":
    unittest.main()
