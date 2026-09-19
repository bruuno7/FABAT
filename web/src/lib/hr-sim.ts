/**
 * Simulador determinista del tramo HappyRobot.
 *
 * Cero LLM a propósito (`consejo/DECISION.md`: "Cero LLM en el núcleo"): reglas
 * explícitas y auditables sobre el texto del aviso. Sirve para dos cosas:
 *  1. que la demo funcione sin API key de HappyRobot (modo `simulated`);
 *  2. tener un oráculo reproducible para comparar contra el extractor real.
 *
 * Cuando `HR_HOOK_TG` está configurado, este módulo NO se usa para el camino real:
 * el extracto llega por `POST /api/hr/events` desde el workflow.
 */
import type {
  Extract,
  HrToMando,
  IncidentType,
  PerfilColor,
  PublicReport,
  TriageColor,
} from "./contract";

type Rule<T> = { value: T; patterns: RegExp[] };

const TYPE_RULES: Rule<IncidentType>[] = [
  {
    value: "medica",
    patterns: [
      /ca[ií]d[ao]/i,
      /desmay/i,
      /inconsciente/i,
      /herid/i,
      /sangr/i,
      /m[ée]dic/i,
      /ambulanc/i,
      /alergi/i,
      /golpe/i,
      /fractur/i,
      /no respira/i,
      /convulsi/i,
    ],
  },
  {
    value: "agresion",
    patterns: [
      /agresi[óo]n/i,
      /pelea/i,
      /robo/i,
      /amenaz/i,
      /insult/i,
      /violencia/i,
      /navaja/i,
    ],
  },
  {
    value: "aglomeracion",
    patterns: [
      /aglomeraci[óo]n/i,
      /empuj/i,
      /avalancha/i,
      /no se puede pasar/i,
      /atasco/i,
      /cola enorme/i,
      /much[ií]sima gente/i,
      /gent[íi]o/i,
    ],
  },
  {
    value: "clima",
    patterns: [
      /lluvi/i,
      /tormenta/i,
      /viento/i,
      /graniz/i,
      /calor/i,
      /fr[íi]o/i,
      /barro/i,
      /inundaci/i,
    ],
  },
  {
    value: "infra",
    patterns: [
      /luz/i,
      /electric/i,
      /valla/i,
      /escenario/i,
      /sonido/i,
      /altavoc/i,
      /ba[ñn]o/i,
      /agua/i,
      /generador/i,
      /pantalla/i,
      /derrum/i,
    ],
  },
];

const SECTORS: Rule<string>[] = [
  { value: "Escenario principal", patterns: [/escenario/i, /main stage/i] },
  { value: "Zona Norte", patterns: [/zona norte/i, /norte/i] },
  { value: "Zona Sur", patterns: [/zona sur/i, /sur\b/i] },
  { value: "Zona Este", patterns: [/zona este/i, /este\b/i] },
  { value: "Zona Oeste", patterns: [/zona oeste/i, /oeste/i] },
  { value: "Entrada", patterns: [/entrada/i, /acceso/i, /puerta/i] },
  { value: "Zona de food trucks", patterns: [/food/i, /comida/i, /barra/i] },
  { value: "Baños", patterns: [/ba[ñn]o/i] },
  { value: "Zona VIP", patterns: [/vip/i, /backstage/i] },
  { value: "Parking", patterns: [/parking/i, /aparcamiento/i] },
  { value: "Campamento", patterns: [/campament/i, /camping/i] },
];

const PERFIL_RULES: Rule<PerfilColor>[] = [
  { value: "menor", patterns: [/ni[ñn][oa]/i, /menor/i, /chaval/i, /cr[íi]o/i] },
  {
    value: "pmr",
    patterns: [
      /silla de ruedas/i,
      /\bpmr\b/i,
      /discapacitad/i,
      /muleta/i,
      /movilidad reducida/i,
    ],
  },
  {
    value: "personal",
    patterns: [
      /seguridad/i,
      /staff/i,
      /trabajador/i,
      /personal del/i,
      /credencial/i,
    ],
  },
  { value: "vip", patterns: [/\bvip\b/i, /artista/i, /invitad/i] },
];

/** Marcadores de riesgo vital (triage negro). */
const BLACK_PATTERNS = [
  /no respira/i,
  /parada card/i,
  /inconsciente/i,
  /atrapad/i,
  /aplastad/i,
  /hemorragia/i,
];

const SEV5_PATTERNS = [
  ...BLACK_PATTERNS,
  /derrum/i,
  /avalancha/i,
  /ni[ñn][oa] solo/i,
  /ni[ñn][oa] sin/i,
  /fuego/i,
  /incendio/i,
  /arma/i,
];
const SEV4_PATTERNS = [
  /grave/i,
  /sangr/i,
  /herid/i,
  /desmay/i,
  /fractur/i,
  /multitud/i,
  /no se puede pasar/i,
  /agresi[óo]n/i,
];
const SEV2_PATTERNS = [/leve/i, /mareo/i, /dolor/i, /peque[ñn]/i, /rasgu[ñn]/i];

function firstMatch<T>(rules: Rule<T>[], text: string): T | undefined {
  for (const rule of rules) {
    if (rule.patterns.some((p) => p.test(text))) return rule.value;
  }
  return undefined;
}

function matches(patterns: RegExp[], text: string): boolean {
  return patterns.some((p) => p.test(text));
}

function guessSeverity(text: string, type: IncidentType | undefined): number {
  if (matches(SEV5_PATTERNS, text)) return 5;
  if (matches(SEV4_PATTERNS, text)) return 4;
  if (type === "aglomeracion" || type === "clima") return 3;
  if (matches(SEV2_PATTERNS, text)) return 2;
  return 3;
}

function severityToTriage(severity: number, text: string): TriageColor {
  if (matches(BLACK_PATTERNS, text)) return "negro";
  if (severity >= 4) return "rojo";
  if (severity === 3) return "amarillo";
  if (severity <= 2) return "verde";
  return "desconocido";
}

function shortSummary(text: string): string {
  const clean = text.replace(/\s+/g, " ").trim();
  if (clean.length <= 96) return clean;
  return `${clean.slice(0, 93)}...`;
}

/** Extracto determinista de un aviso. Misma forma que el `extract` del contrato. */
export function simulateExtract(report: PublicReport): Extract {
  const text = report.text ?? "";
  const incident_type = firstMatch(TYPE_RULES, text) ?? "otro";
  const sector =
    report.location_hint ??
    firstMatch(SECTORS, text) ??
    "Sin ubicación precisa";
  const severity = guessSeverity(text, incident_type);
  const perfil_color =
    report.reporter?.perfil_color ?? firstMatch(PERFIL_RULES, text) ?? "adulto";

  return {
    incident_type,
    sector,
    severity,
    triage_color: severityToTriage(severity, text),
    perfil_color,
    summary: shortSummary(text),
  };
}

/** Respuesta del agente al ciudadano. Plantillas fijas, sin inventar recursos. */
export function simulateReply(extract: Extract): string {
  const sector = extract.sector ?? "tu zona";
  switch (extract.triage_color) {
    case "negro":
    case "rojo":
      return `Recibido. Aviso prioritario en ${sector}. Movilizamos recursos y te confirmamos por aquí. Si la persona no responde, no la muevas.`;
    case "amarillo":
      return `Recibido. Priorizamos tu aviso en ${sector} y lo pasamos a la mesa de decisión.`;
    case "verde":
      return `Recibido. Aviso registrado en ${sector}; un equipo lo revisa. Gracias.`;
    default:
      return `Recibido tu aviso. Lo estamos clasificando en la mesa de decisión.`;
  }
}

/**
 * Convierte un aviso en la secuencia de eventos que emitiría el workflow
 * `fa-entrada-tg`: extract_ready + agent_reply (+ needs_human si es grave).
 */
export function simulateHrLeg(report: PublicReport): HrToMando[] {
  const extract = simulateExtract(report);
  const correlation_id = report.correlation_id ?? `sim-${Date.now()}`;
  const base = {
    correlation_id,
    channel: report.channel,
    chat_id: report.reporter?.chat_id,
    hr_run_id: `sim-run-${correlation_id}`,
  };

  const events: HrToMando[] = [
    { event: "extract_ready", ...base, extract },
    {
      event: "agent_reply",
      ...base,
      extract,
      reply_text: simulateReply(extract),
    },
  ];

  if (extract.triage_color === "rojo" || extract.triage_color === "negro") {
    events.push({ event: "needs_human", ...base, extract });
  }

  return events;
}
