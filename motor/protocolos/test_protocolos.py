"""Pruebas de `protocolos.json`, del validador y de la semántica de referencia.

    python3 -m unittest motor.protocolos.test_protocolos -v
"""
from __future__ import annotations

import copy
import unittest

from motor.protocolos import can_dispatch, first_flag, load, matches, next_slot
from motor.protocolos.validate import MAX_QUESTION_WORDS, validate, words

REQUIRED = {
    "unresponsive_person", "breathing_choking", "heat_illness", "severe_bleeding", "seizure", "allergic_reaction",
    "intoxication", "fall_trauma", "crowd_crush", "gate_saturation", "fight_assault", "sexual_violence",
    "chemical_submission", "lost_child", "vulnerable_person", "smoke_fire", "storm_lightning", "wind_structure",
    "power_outage", "water_supplies_out", "suspicious_object_threat", "infrastructure_failure", "unknown"}
SENSITIVE = {"sexual_violence", "chemical_submission", "lost_child", "suspicious_object_threat"}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = load()
        cls.by_id = {p["id"]: p for p in cls.doc["protocols"]}

    def broken(self, mutate):
        doc = copy.deepcopy(self.doc)
        mutate(doc)
        return validate(doc)

    def assertRejected(self, mutate, fragment):
        errs = self.broken(mutate)
        self.assertTrue(any(fragment in e for e in errs), f"esperaba un error con «{fragment}», hubo: {errs[:3]}")


class TestFichero(Base):
    def test_el_fichero_real_es_valido(self):
        self.assertEqual(validate(self.doc), [])

    def test_cobertura(self):
        self.assertGreaterEqual(len(self.doc["protocols"]), 22)
        self.assertEqual(REQUIRED - set(self.by_id), set())
        self.assertEqual(self.doc["protocols"][-1]["id"], "unknown")

    def test_sensibles(self):
        self.assertEqual({p["id"] for p in self.doc["protocols"] if p["sensitive"]}, SENSITIVE)
        for pid in SENSITIVE:
            ext = self.by_id[pid]["handoff"]["external"]
            self.assertEqual((ext["kind"], ext["requires_approval"]), ("police", True), pid)
        for pid in ("sexual_violence", "chemical_submission"):
            self.assertTrue(self.by_id[pid]["handoff"]["external"]["requires_consent"], pid)
        # NS-25: en violencia sexual solo «¿estás en un sitio seguro?» y «¿dónde estás?»
        self.assertEqual([s["id"] for s in self.by_id["sexual_violence"]["slots"]], ["safe_now", "location_point"])
        self.assertNotIn("aggression", {i["id"] for i in self.by_id["sexual_violence"]["instructions"]})

    def test_preguntas_cortas_y_bilingues(self):
        for p in self.doc["protocols"]:
            self.assertLessEqual(len(p["slots"]), 5, p["id"])
            for s in p["slots"]:
                for lang in ("es", "en"):
                    self.assertLessEqual(words(s["question"][lang]), MAX_QUESTION_WORDS, f"{p['id']}.{s['id']}.{lang}")

    def test_aviso_de_seguridad(self):
        self.assertIn("SIMULACIÓN", self.doc["disclaimer"]["es"])
        self.assertIn("112", self.doc["disclaimer"]["es"])

    def test_lo_medico_se_envia_solo_con_la_ubicacion(self):
        for p in self.doc["protocols"]:
            if p["family"] == "medical":
                self.assertEqual(p["dispatch_as_soon_as"], ["location_point"], p["id"])

    def test_textos_validados_del_anexo_c_no_se_tocan(self):
        textos = {i["id"]: " ".join(i["steps"]["es"]) for p in self.doc["protocols"] for i in p["instructions"]}
        self.assertEqual(textos["crowd_pressure"], "No empujes. Brazos delante del pecho. No te agaches. Sal en diagonal hacia los lados cuando afloje.")
        self.assertEqual(textos["seizure"], "No la sujetes ni le metas nada en la boca. Aparta lo que pueda golpearla. Cuando pare, ponla de lado.")
        self.assertEqual(textos["suspicious_object"], "No lo toques ni lo muevas. Aléjate y díselo al personal con chaleco.")
        self.assertEqual(textos["fire_or_structure"], "Aléjate de ahí andando, sin correr, y no vuelvas. Avisa al personal con chaleco.")


class TestValidador(Base):
    def p(self, doc, pid="unresponsive_person"):
        return next(p for p in doc["protocols"] if p["id"] == pid)

    def test_id_de_protocolo_repetido(self):
        self.assertRejected(lambda d: d["protocols"].insert(0, copy.deepcopy(d["protocols"][0])), "id repetido")

    def test_id_de_slot_repetido(self):
        self.assertRejected(lambda d: self.p(d)["slots"].__setitem__(4, copy.deepcopy(self.p(d)["slots"][1])), "slot repetido")

    def test_ask_if_a_slot_inexistente(self):
        self.assertRejected(lambda d: self.p(d)["slots"][2].__setitem__("ask_if", {"no_existe": True}), "slot inexistente")

    def test_ask_if_a_slot_posterior(self):
        self.assertRejected(lambda d: self.p(d)["slots"][1].__setitem__("ask_if", {"breathing_normal": False}), "slots anteriores")

    def test_ask_if_con_valor_imposible(self):
        self.assertRejected(lambda d: self.p(d)["slots"][2].__setitem__("ask_if", {"responsive": "quizá"}), "no válido para 'responsive'")

    def test_instruccion_referenciada_que_no_existe(self):
        self.assertRejected(lambda d: self.p(d)["red_flags"][0]["then"].__setitem__("instruction", "fantasma"), "no está en las instrucciones")

    def test_pregunta_larga(self):
        larga = " ".join(["palabra"] * 17)
        self.assertRejected(lambda d: self.p(d)["slots"][1]["question"].__setitem__("es", larga), "17 palabras")

    def test_falta_el_ingles(self):
        self.assertRejected(lambda d: self.p(d)["slots"][1]["question"].pop("en"), "falta el texto 'en'")
        self.assertRejected(lambda d: self.p(d)["instructions"][0]["steps"].pop("en"), "faltan los pasos en 'en'")
        self.assertRejected(lambda d: d["global"]["opening"].pop("en"), "global.opening")

    def test_fuentes_vacias(self):
        self.assertRejected(lambda d: self.p(d).__setitem__("sources", []), "'sources' vacío")
        self.assertRejected(lambda d: self.p(d).__setitem__("sources", ["un libro"]), "URL abierta")
        self.assertRejected(lambda d: self.p(d)["instructions"][0].__setitem__("source", ""), "'source' vacío")

    def test_mas_de_cinco_slots(self):
        def mutate(d):
            extra = copy.deepcopy(self.p(d)["slots"][-1])
            extra["id"] = "sexto"
            self.p(d)["slots"].append(extra)
        self.assertRejected(mutate, "máximo 5")

    def test_critico_detras_de_no_critico(self):
        self.assertRejected(lambda d: self.p(d)["slots"][0].__setitem__("critical", False), "ordenados por criticidad")

    def test_enum_sin_opciones(self):
        self.assertRejected(lambda d: self.p(d)["slots"][3].pop("options"), "necesita 'options'")

    def test_riesgo_vital_sin_envio_inmediato(self):
        self.assertRejected(lambda d: self.p(d)["red_flags"][0]["then"].__setitem__("dispatch_now", False), "nunca se retrasa")

    def test_externo_sin_aprobacion(self):
        self.assertRejected(lambda d: self.p(d)["handoff"]["external"].__setitem__("requires_approval", False), "requires_approval")

    def test_envio_que_depende_de_un_slot_condicional(self):
        self.assertRejected(lambda d: self.p(d)["dispatch_as_soon_as"].append("breathing_normal"), "condicional")

    def test_misma_instruccion_con_otro_texto(self):
        def mutate(d):
            ins = next(i for i in self.p(d, "seizure")["instructions"] if i["id"] == "cpr_hands_only")
            ins["steps"]["es"][0] = "Otro texto."
        self.assertRejected(mutate, "otro texto")

    def test_tipo_de_mando_desconocido(self):
        errs = self.broken(lambda d: self.p(d).__setitem__("mando_type_hint", "inventado"))
        self.assertTrue(any("no es un tipo de Mando" in e for e in errs) or errs == [])  # [] si no hay taxonomía a mano
        self.assertTrue(any("no es un tipo de Mando" in e for e in validate(
            (lambda d: (self.p(d).__setitem__("mando_type_hint", "inventado"), d)[1])(copy.deepcopy(self.doc)), taxonomy={"cardiac_arrest"})))

    def test_unknown_debe_ir_el_ultimo(self):
        self.assertRejected(lambda d: d["protocols"].insert(0, d["protocols"].pop()), "debe ser el último")


class TestSemantica(Base):
    def test_true_no_es_uno(self):
        self.assertFalse(matches({"people_count": 1}, {"people_count": True}))
        self.assertFalse(matches({"responsive": True}, {"responsive": 1}))
        self.assertTrue(matches({"people_count": {"gte": 2}}, {"people_count": 3}))
        self.assertFalse(matches({"people_count": {"gte": 2}}, {}))
        self.assertTrue(matches({}, {}))

    def test_parada_reconocida_con_dos_preguntas(self):
        p = self.by_id["unresponsive_person"]
        answers = {"location_point": {"zone": "front_pit", "point": "valla izquierda"}}
        self.assertTrue(can_dispatch(p, answers))          # se envía ya, antes de preguntar nada más
        self.assertEqual(next_slot(p, answers)["id"], "responsive")
        answers["responsive"] = False
        self.assertEqual(first_flag(p, answers)["instruction"], "not_responding")   # texto validado, de inmediato
        self.assertEqual(next_slot(p, answers)["id"], "breathing_normal")
        answers["breathing_normal"] = False
        then = first_flag(p, answers)
        self.assertEqual((then["instruction"], then["severity_min"], then["life_risk"]), ("cpr_hands_only", 10, True))
        self.assertIsNone(next_slot(p, answers))           # con RCP en marcha no se pregunta nada más

    def test_no_se_si_respira_es_el_peor_caso(self):
        p = self.by_id["unresponsive_person"]
        answers = {"location_point": "x", "responsive": False, "breathing_normal": "unknown"}
        self.assertEqual(next_slot(p, answers)["id"], "breathing_description")
        answers["breathing_description"] = "gasping_or_noisy"
        self.assertEqual(first_flag(p, answers)["instruction"], "cpr_hands_only")

    def test_inconsciente_que_respira_va_de_lado(self):
        p = self.by_id["unresponsive_person"]
        then = first_flag(p, {"location_point": "x", "responsive": False, "breathing_normal": True})
        self.assertEqual(then["instruction"], "unconscious_breathing")

    def test_calor_con_confusion_es_riesgo_vital(self):
        then = first_flag(self.by_id["heat_illness"], {"location_point": "x", "responsive": True, "confused": True})
        self.assertEqual((then["instruction"], then["life_risk"], then["severity_min"]), ("heat_cool_now", True, 9))

    def test_violencia_sexual_dos_preguntas_y_nada_mas(self):
        p = self.by_id["sexual_violence"]
        answers = {}
        asked = []
        while (slot := next_slot(p, answers)) is not None:
            asked.append(slot["id"])
            answers[slot["id"]] = True if slot["type"] == "bool" else "x"
        self.assertEqual(asked, ["safe_now", "location_point"])
        self.assertEqual(first_flag(p, answers)["instruction"], "violet")

    def test_toda_combinacion_de_un_aviso_medico_tiene_instruccion(self):
        for p in self.doc["protocols"]:
            if p["family"] != "medical":
                continue
            for responsive in (True, False, "unknown"):
                slot_ids = {s["id"] for s in p["slots"]}
                answers = {"location_point": "x"}
                if "responsive" in slot_ids:
                    answers["responsive"] = responsive
                then = first_flag(p, answers)
                if "responsive" in slot_ids and responsive is not True:
                    self.assertIsNotNone(then, f"{p['id']} responsive={responsive}")
                    self.assertTrue(then["dispatch_now"], p["id"])


if __name__ == "__main__":
    unittest.main()
