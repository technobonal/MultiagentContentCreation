/**
 * aprobacion.ts — Lógica pura de la aprobación humana (HITL) en el lienzo, sin React.
 * Decide cuándo se espera una decisión, qué campos se pueden editar y arma el cuerpo del POST
 * a /api/runs/{id}/aprobacion con SOLO lo que la persona cambió. El servidor vuelve a validar todo
 * (campos, límites, «texto_antes») y es quien emite los eventos `editada` y `aprobada`.
 */
import type { Estado } from "../timeline/types.ts";

/** Un campo de texto que la persona puede editar: lo que hoy está dibujado en el lienzo. */
export interface CampoEditable {
  readonly slide: number;
  readonly campo: string;
  readonly texto: string;
}

/** Borradores de la persona, por clave «slide:campo». Un campo sin borrador sigue como está dibujado. */
export type Borradores = Readonly<Record<string, string>>;

/** Una edición tal como la espera el servidor. */
export interface EdicionEnviada {
  readonly slide: number;
  readonly campo: string;
  readonly texto: string;
}

/** El semáforo que calcula el servidor. */
export interface Informe {
  readonly visto_bueno: boolean;
  readonly generales: readonly string[];
  readonly slides: readonly {
    readonly slide: number;
    readonly color: "verde" | "rojo";
    readonly motivos: readonly string[];
    readonly avisos: readonly string[];
  }[];
}

/** Hace falta una excepción si el servidor no da el visto bueno o si la persona editó algo (no se re-verifica). */
export function necesitaExcepcion(informe: Informe, cambios: number): boolean {
  return !informe.visto_bueno || cambios > 0;
}

/** Motivos del semáforo de un slide que no son un hallazgo (esos ya se muestran con su explicación). */
export function motivosSinHallazgo(informe: Informe, slide: number): readonly string[] {
  return informe.slides.find((s) => s.slide === slide)?.motivos.filter((m) => !m.startsWith("Hallazgo ")) ?? [];
}

/** Pide el semáforo del run; null si no se pudo obtener (entonces no se ofrece aprobar). */
export async function pedirInforme(runId: string, llamar: typeof fetch = fetch): Promise<Informe | null> {
  try {
    const respuesta = await llamar(`/api/runs/${encodeURIComponent(runId)}/informe`);
    if (!respuesta.ok) return null;
    const json = (await respuesta.json()) as Partial<Informe> | null;
    return typeof json?.visto_bueno === "boolean" && Array.isArray(json.slides) && Array.isArray(json.generales)
      ? (json as Informe)
      : null;
  } catch {
    return null;
  }
}

/** Cuerpo del POST: ediciones (puede ser vacío), comentario opcional y, en rojo, la excepción. */
export interface CuerpoDecision {
  readonly ediciones: readonly EdicionEnviada[];
  readonly comentario?: string;
  readonly excepcion?: string;
}

/** Agentes que se pueden señalar como responsables al rechazar. */
export const RESPONSABLES = ["redactor", "revisor", "director_arte", "estratega"] as const;
export type Responsable = (typeof RESPONSABLES)[number];

/** Lo que la persona escribe para rechazar; «» y null significan «sin indicar». */
export interface BorradorRechazo {
  readonly motivo: string;
  readonly responsable: Responsable | "";
  readonly slide: number | null;
  readonly esperado: string;
}

export const RECHAZO_VACIO: BorradorRechazo = { motivo: "", responsable: "", slide: null, esperado: "" };

/** Cuerpo del POST para rechazar: solo el motivo es obligatorio y lo vacío no se envía. */
export interface CuerpoRechazo {
  readonly rechazo: {
    readonly motivo: string;
    readonly responsable?: Responsable;
    readonly slide?: number;
    readonly esperado?: string;
  };
}

export function cuerpoRechazo(b: BorradorRechazo): CuerpoRechazo {
  const esperado = b.esperado.trim();
  return {
    rechazo: {
      motivo: b.motivo.trim(),
      ...(b.responsable === "" ? {} : { responsable: b.responsable }),
      ...(b.slide === null ? {} : { slide: b.slide }),
      ...(esperado === "" ? {} : { esperado }),
    },
  };
}

export type ResultadoEnvio =
  | { readonly ok: true; readonly ediciones: number }
  | { readonly ok: false; readonly motivos: readonly string[] };

/** Clave de un campo en los borradores. */
export function claveCampo(slide: number, campo: string): string {
  return `${slide}:${campo}`;
}

/** True mientras el run espera la decisión: pidió la aprobación y todavía no hay decisión ni cierre. */
export function esperaAprobacion(estado: Estado): boolean {
  return estado.revision !== null && estado.decision === null && estado.final === null;
}

/** Campos dibujados que se pueden editar, ordenados por slide (dentro de un slide, en el orden en que se dibujaron). */
export function camposEditables(estado: Estado): readonly CampoEditable[] {
  const campos: CampoEditable[] = [];
  const slides = Object.keys(estado.lienzo.textos)
    .map(Number)
    .sort((a, b) => a - b);
  for (const slide of slides) {
    const porCampo = estado.lienzo.textos[slide] ?? {};
    for (const [campo, texto] of Object.entries(porCampo)) {
      campos.push({ slide, campo, texto });
    }
  }
  return campos;
}

/** Texto que la persona ve en un campo: su borrador si lo hay, y si no, el dibujado. */
export function textoActual(borradores: Borradores, campo: CampoEditable): string {
  return borradores[claveCampo(campo.slide, campo.campo)] ?? campo.texto;
}

/** Campos cuyo borrador (sin espacios en los bordes) difiere de lo dibujado. Un borrador vacío cuenta: el servidor lo rechaza. */
export function camposModificados(estado: Estado, borradores: Borradores): readonly CampoEditable[] {
  return camposEditables(estado).filter((c) => {
    const borrador = borradores[claveCampo(c.slide, c.campo)];
    return borrador !== undefined && borrador.trim() !== c.texto;
  });
}

/** Cuerpo del POST: solo los campos modificados y el comentario si no está vacío. */
export function cuerpoDecision(estado: Estado, borradores: Borradores, comentario: string, excepcion = ""): CuerpoDecision {
  const ediciones = camposModificados(estado, borradores).map((c) => ({
    slide: c.slide,
    campo: c.campo,
    texto: textoActual(borradores, c).trim(),
  }));
  const limpio = comentario.trim();
  const porque = excepcion.trim();
  return { ediciones, ...(limpio === "" ? {} : { comentario: limpio }), ...(porque === "" ? {} : { excepcion: porque }) };
}

/** Motivos de un error del servidor: «motivos» (422 y 409) o «detail» (404); si no, un mensaje con el código. */
function motivosDeError(cuerpo: unknown, status: number): readonly string[] {
  if (typeof cuerpo === "object" && cuerpo !== null) {
    const { motivos, detail } = cuerpo as { motivos?: unknown; detail?: unknown };
    if (Array.isArray(motivos) && motivos.every((m) => typeof m === "string") && motivos.length > 0) {
      return motivos as string[];
    }
    if (typeof detail === "string") return [detail];
  }
  return [`El servidor respondió ${status}.`];
}

/** Envía la decisión. Nunca lanza: devuelve ok o los motivos para mostrárselos a la persona. */
export async function enviarAprobacion(
  runId: string,
  cuerpo: CuerpoDecision | CuerpoRechazo,
  llamar: typeof fetch = fetch,
): Promise<ResultadoEnvio> {
  let respuesta: Response;
  try {
    respuesta = await llamar(`/api/runs/${encodeURIComponent(runId)}/aprobacion`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cuerpo),
    });
  } catch {
    return { ok: false, motivos: ["No se pudo conectar con el servidor."] };
  }
  let json: unknown = null;
  try {
    json = await respuesta.json();
  } catch {
    // Sin cuerpo JSON: se usa el código de estado.
  }
  if (respuesta.ok) {
    const ediciones = (json as { ediciones?: unknown } | null)?.ediciones;
    return { ok: true, ediciones: typeof ediciones === "number" ? ediciones : 0 };
  }
  return { ok: false, motivos: motivosDeError(json, respuesta.status) };
}
