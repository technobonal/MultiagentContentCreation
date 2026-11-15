/**
 * sello.ts — Texto del sello de revisión. Lo calcula código a partir del ledger
 * (nunca un LLM) y solo existe cuando ya hay afirmaciones verificadas.
 */
import { calcularSello } from "../timeline/reducer.ts";
import type { Estado } from "../timeline/types.ts";

/** Devuelve "N de M afirmaciones respaldadas" en el idioma de salida, o null si el ledger está vacío. */
export function textoDelSello(estado: Estado): string | null {
  const sello = calcularSello(estado.ledger);

  // Sin afirmaciones verificadas todavía no hay sello que mostrar.
  if (sello.afirmaciones_totales === 0) return null;

  const n = sello.afirmaciones_respaldadas;
  const m = sello.afirmaciones_totales;

  // Idioma de la corrida; por defecto español.
  if (estado.run?.idioma_salida === "pt-BR") {
    return `${n} de ${m} afirmações respaldadas`;
  }
  return `${n} de ${m} afirmaciones respaldadas`;
}