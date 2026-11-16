/**
 * camposCalculados.ts — Campos del slide de fuentes que no vienen de eventos de texto:
 * los calcula código a partir del estado (nunca un LLM).
 *  - sello_revision: "N de M afirmaciones respaldadas", desde el ledger.
 *  - fuente_atribucion y fuente_licencia: desde run_iniciada (estado.run.fuente).
 * Un evento de texto con el mismo nombre tiene prioridad (lo resuelve el llamador).
 */
import { textoDelSello } from "./sello.ts";
import type { Estado } from "../timeline/types.ts";

/** Texto calculado de un campo, o undefined si el campo no es calculado o todavía no hay dato. */
export function textoCampoCalculado(estado: Estado, nombre: string): string | undefined {
  // El sello solo existe cuando el ledger ya tiene afirmaciones.
  if (nombre === "sello_revision") return textoDelSello(estado) ?? undefined;

  // Atribución y licencia de la fuente: salen de la corrida, no del redactor.
  if (nombre === "fuente_atribucion") return estado.run?.fuente.atribucion;
  if (nombre === "fuente_licencia") return estado.run?.fuente.licencia;

  // Cualquier otro campo no es calculado.
  return undefined;
}