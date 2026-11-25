/**
 * espera.ts — Lógica pura del aviso «esperando al servidor», sin React.
 * Mientras un run en vivo sigue abierto y no llegan eventos, el lienzo parece congelado (por ejemplo cuando Groq
 * no tiene cupo y el limitador duerme). El aviso aparece tras unos segundos de silencio y no afirma la causa.
 */
import type { Estado } from "../timeline/types.ts";
import { esperaAprobacion } from "./aprobacion.ts";

/** Segundos sin eventos a partir de los cuales se muestra el aviso. */
export const SILENCIO_MIN_SEG = 4;

/** True si el silencio es una espera del servidor: el run empezó, no terminó y no espera a una persona. */
export function puedeEstarEsperando(estado: Estado): boolean {
  return estado.ultimoSeq > 0 && estado.final === null && !esperaAprobacion(estado);
}

/** Texto del aviso, o null mientras el silencio es normal. */
export function textoEspera(segundosSinEventos: number): string | null {
  if (segundosSinEventos < SILENCIO_MIN_SEG) return null;
  return `Esperando al servidor… ${Math.floor(segundosSinEventos)} s sin eventos (puede ser espera de cupo del modelo).`;
}
