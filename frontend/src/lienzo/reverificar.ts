/**
 * reverificar.ts — Lógica pura para pedir que un slide se vuelva a verificar sin cerrar el run (A5).
 * Arma el cuerpo del POST a /api/runs/{id}/reverificar: «edicion» (con los campos que la persona cambió) o
 * «agente» (el corrector reescribe). El servidor vuelve a validar todo y emite los eventos nuevos por el SSE.
 */
import type { Estado } from "../timeline/types.ts";
import { camposModificados, textoActual } from "./aprobacion.ts";
import type { Borradores } from "./aprobacion.ts";

/** Cuerpo del POST para re-verificar un slide. */
export type CuerpoReverificar =
  | { readonly slide: number; readonly modo: "edicion"; readonly ediciones: readonly { slide: number; campo: string; texto: string }[] }
  | { readonly slide: number; readonly modo: "agente" };

/** Cuerpo de «edición»: solo los campos de ESE slide que la persona cambió (texto recortado). */
export function cuerpoEdicion(estado: Estado, borradores: Borradores, slide: number): CuerpoReverificar {
  const ediciones = camposModificados(estado, borradores)
    .filter((c) => c.slide === slide)
    .map((c) => ({ slide: c.slide, campo: c.campo, texto: textoActual(borradores, c).trim() }));
  return { slide, modo: "edicion", ediciones };
}

/** Cuántos campos de ese slide cambió la persona (para habilitar «Verificar mi edición»). */
export function cambiosDelSlide(estado: Estado, borradores: Borradores, slide: number): number {
  return camposModificados(estado, borradores).filter((c) => c.slide === slide).length;
}

export type ResultadoReverificar =
  | { readonly ok: true }
  | { readonly ok: false; readonly motivos: readonly string[] };

/** ¿El error es por haber agotado las re-verificaciones del run? (el único motivo que las menciona). */
export function esTopeReverificacion(motivos: readonly string[]): boolean {
  return motivos.some((m) => /re-verificaciones/i.test(m));
}

/** Motivos de un error del servidor: «motivos» (422/409) o «detail» (404); si no, un mensaje con el código. */
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

/**
 * Pide re-verificar un slide. Nunca lanza: devuelve ok o los motivos. Las verificaciones nuevas llegan por el SSE,
 * así que al salir bien no hay nada que leer aquí.
 */
export async function pedirReverificacion(
  runId: string,
  cuerpo: CuerpoReverificar,
  llamar: typeof fetch = fetch,
): Promise<ResultadoReverificar> {
  let respuesta: Response;
  try {
    respuesta = await llamar(`/api/runs/${encodeURIComponent(runId)}/reverificar`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cuerpo),
    });
  } catch {
    return { ok: false, motivos: ["No se pudo conectar con el servidor."] };
  }
  if (respuesta.ok) return { ok: true };
  let json: unknown = null;
  try {
    json = await respuesta.json();
  } catch {
    // Sin cuerpo JSON: se usa el código de estado.
  }
  return { ok: false, motivos: motivosDeError(json, respuesta.status) };
}
