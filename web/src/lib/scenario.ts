/**
 * Escenarios del Festival Abierto para el panel de simulación.
 * Día 1 = incidencias menores. Día 2 = el plan deja de valer.
 * Datos de demo; no son datos reales de un evento.
 */
import type { PerfilColor } from "./contract";

export type ScenarioItem = {
  id: string;
  text: string;
  reporter: string;
  perfil_color: PerfilColor;
  location_hint?: string;
};

export type Scenario = {
  id: "dia1" | "dia2";
  name: string;
  subtitle: string;
  items: ScenarioItem[];
};

export const SCENARIOS: Scenario[] = [
  {
    id: "dia1",
    name: "Día 1 — carga normal",
    subtitle:
      "Incidencias menores y dispersas. El plan aguanta; sirve para aprender el recinto.",
    items: [
      {
        id: "d1-1",
        text: "Se ha desmayado una chica en la zona norte, está consciente pero muy pálida",
        reporter: "Lucía",
        perfil_color: "adulto",
      },
      {
        id: "d1-2",
        text: "Muchísima gente en la entrada, no se puede pasar, hay empujones",
        reporter: "Marcos",
        perfil_color: "adulto",
      },
      {
        id: "d1-3",
        text: "Un chaval se ha caído cerca del escenario principal y se ha hecho daño en el tobillo",
        reporter: "Aitana",
        perfil_color: "menor",
      },
      {
        id: "d1-4",
        text: "No hay luz en los baños de la zona oeste y está todo a oscuras",
        reporter: "Personal de zona",
        perfil_color: "personal",
      },
      {
        id: "d1-5",
        text: "Una señora en silla de ruedas no encuentra el acceso adaptado en la entrada",
        reporter: "Nerea",
        perfil_color: "pmr",
      },
      {
        id: "d1-6",
        text: "Hay una pelea en la zona de food trucks, dos personas discutiendo muy fuerte",
        reporter: "Iván",
        perfil_color: "adulto",
      },
      {
        id: "d1-7",
        text: "Empieza a llover fuerte y la gente se acumula bajo la carpa de la zona este",
        reporter: "Paula",
        perfil_color: "adulto",
      },
      {
        id: "d1-8",
        text: "Un mareo leve en la zona sur, la persona ya está mejor",
        reporter: "Sergio",
        perfil_color: "adulto",
      },
    ],
  },
  {
    id: "dia2",
    name: "Día 2 — el plan deja de valer",
    subtitle:
      "Aforo máximo, clima adverso y varias crisis a la vez. La demanda supera la dotación.",
    items: [
      {
        id: "d2-1",
        text: "Persona inconsciente y no respira cerca del escenario principal, necesitamos ambulancia ya",
        reporter: "Rocío",
        perfil_color: "adulto",
      },
      {
        id: "d2-2",
        text: "Avalancha en la entrada, alguien ha caído al suelo y la gente sigue empujando",
        reporter: "Anónimo",
        perfil_color: "adulto",
      },
      {
        id: "d2-3",
        text: "Un niño solo llorando en la zona VIP, no encuentra a sus padres",
        reporter: "Celia",
        perfil_color: "menor",
      },
      {
        id: "d2-4",
        text: "Agresión con navaja en el parking, hay una persona herida",
        reporter: "Vigilante",
        perfil_color: "personal",
      },
      {
        id: "d2-5",
        text: "Se ha caído una valla y hay gente atrapada en la zona sur",
        reporter: "Hugo",
        perfil_color: "adulto",
      },
      {
        id: "d2-6",
        text: "Tormenta fuerte, se ha inundado el campamento y hay barro por todas partes",
        reporter: "Elena",
        perfil_color: "adulto",
      },
      {
        id: "d2-7",
        text: "Se ha caído el generador, todo el escenario principal sin luz ni sonido",
        reporter: "Técnico de sonido",
        perfil_color: "personal",
      },
      {
        id: "d2-8",
        text: "Chica con movilidad reducida atrapada en la aglomeración de la zona este, está en el suelo",
        reporter: "Dani",
        perfil_color: "pmr",
      },
    ],
  },
];

export function getScenario(id: string): Scenario | undefined {
  return SCENARIOS.find((s) => s.id === id);
}
