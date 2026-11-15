// ---------------------------------------------------------------------------
// ordenador.ts — Deja una lista de eventos lista para el reductor.
// Ordena por seq, descarta repetidos idénticos y reporta como problema todo lo
// que el reductor no debe recibir: seq inválido, run_id mezclado, repetido con
// contenido distinto, hueco e inicio distinto de 1. Es una función pura: no muta
// la entrada. Si hay problemas, quien la llama NO debe reproducir la lista.
// ---------------------------------------------------------------------------
import type { Evento } from "./types.ts";

// Tipos de problema que el ordenador sabe detectar.
export type CodigoProblema =
  | "seq_invalido"
  | "run_mezclado"
  | "seq_repetido_distinto"
  | "inicio_distinto_de_1"
  | "hueco";

// Un problema detectado: su tipo, el seq involucrado (null si no es un número válido) y un detalle legible.
export interface Problema {
  readonly codigo: CodigoProblema;
  readonly seq: number | null;
  readonly detalle: string;
}

// Resultado del ordenador: eventos limpios, problemas y un atajo `ok` (sin problemas).
export interface ResultadoOrden {
  readonly eventos: readonly Evento[];
  readonly problemas: readonly Problema[];
  readonly ok: boolean;
}

// Convierte un valor en un texto canónico (claves ordenadas, sin claves undefined)
// para comparar eventos por contenido sin depender del orden de las claves.
function canonico(valor: unknown): string {
  // undefined no tiene representación JSON: se marca aparte.
  if (valor === undefined) return "undefined";
  // Números, textos, booleanos y null se serializan directamente.
  if (valor === null || typeof valor !== "object") return JSON.stringify(valor);
  // Las listas conservan su orden.
  if (Array.isArray(valor)) return `[${valor.map((v) => canonico(v)).join(",")}]`;
  const objeto = valor as Record<string, unknown>;
  // Se ignoran las claves con undefined (JSON también las omite) y se ordenan las demás.
  const claves = Object.keys(objeto)
    .filter((k) => objeto[k] !== undefined)
    .sort();
  return `{${claves.map((k) => `${JSON.stringify(k)}:${canonico(objeto[k])}`).join(",")}}`;
}

// Redacta el detalle de un hueco: faltan los seq desde..hasta antes de `despues`.
function detalleHueco(desde: number, hasta: number, despues: number): string {
  // Un solo seq faltante se escribe en singular.
  if (desde === hasta) return `Falta el seq ${desde} antes del seq ${despues}.`;
  return `Faltan los seq ${desde} a ${hasta} antes del seq ${despues}.`;
}

// Agrupa los eventos de un mismo seq y recuerda si todos tienen el mismo contenido.
interface Grupo {
  readonly primero: Evento;
  readonly canon: string;
  cantidad: number;
  iguales: boolean;
}

// Ordenador principal: devuelve eventos limpios y la lista de problemas.
export function ordenar(eventos: readonly Evento[]): ResultadoOrden {
  const problemas: Problema[] = [];

  // 1) Separa los eventos cuyo seq no es un entero >= 1.
  const validos: Evento[] = [];
  for (const evento of eventos) {
    // Un seq así no se puede ubicar en la secuencia: se reporta y se descarta.
    if (!Number.isInteger(evento.seq) || evento.seq < 1) {
      problemas.push({
        codigo: "seq_invalido",
        seq: Number.isFinite(evento.seq) ? evento.seq : null,
        detalle: `Evento con seq inválido (${String(evento.seq)}); se descarta.`,
      });
      continue;
    }
    validos.push(evento);
  }

  // 2) Ordena por seq (copia propia: la entrada no se toca).
  validos.sort((a, b) => a.seq - b.seq);

  // 3) El run de referencia es el del evento con menor seq; los demás se excluyen.
  const primero = validos[0];
  const runReferencia = primero === undefined ? null : primero.run_id;
  const delRun: Evento[] = [];
  for (const evento of validos) {
    // Un evento de otro run no pertenece a esta secuencia.
    if (evento.run_id !== runReferencia) {
      problemas.push({
        codigo: "run_mezclado",
        seq: evento.seq,
        detalle: `Evento del run ${evento.run_id}; la secuencia es del run ${String(runReferencia)}.`,
      });
      continue;
    }
    delRun.push(evento);
  }

  // 4) Agrupa por seq (el Map conserva el orden ascendente) y compara contenidos.
  const grupos = new Map<number, Grupo>();
  for (const evento of delRun) {
    const canon = canonico(evento);
    const previo = grupos.get(evento.seq);
    if (previo === undefined) {
      // Primer evento con este seq.
      grupos.set(evento.seq, { primero: evento, canon, cantidad: 1, iguales: true });
    } else {
      // Repetido: se cuenta y se marca si el contenido difiere del primero.
      previo.cantidad += 1;
      if (previo.canon !== canon) previo.iguales = false;
    }
  }

  // 5) Un repetido idéntico pasa una sola vez; uno con contenido distinto no pasa ninguno.
  const limpios: Evento[] = [];
  for (const [seq, grupo] of grupos) {
    if (grupo.iguales) {
      limpios.push(grupo.primero);
    } else {
      problemas.push({
        codigo: "seq_repetido_distinto",
        seq,
        detalle: `El seq ${seq} aparece ${grupo.cantidad} veces con contenido distinto; no se aplica ninguna.`,
      });
    }
  }

  // 6) Busca huecos sobre todos los seq vistos (incluidos los conflictivos, para no duplicar el aviso).
  let anterior = 0;
  for (const seq of grupos.keys()) {
    // Si no es el siguiente número, faltan eventos antes de este seq.
    if (seq !== anterior + 1) {
      problemas.push({
        // Si todavía no hubo ningún seq, el problema es que no se empieza en 1.
        codigo: anterior === 0 ? "inicio_distinto_de_1" : "hueco",
        seq,
        detalle: detalleHueco(anterior + 1, seq - 1, seq),
      });
    }
    anterior = seq;
  }

  return { eventos: limpios, problemas, ok: problemas.length === 0 };
}