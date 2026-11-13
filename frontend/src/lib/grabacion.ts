// ---------------------------------------------------------------------------
// grabacion.ts — Carga de las secuencias grabadas (contracts/recordings/*.json).
// Se empaquetan con import.meta.glob y se validan contra recording.schema.json
// antes de entregarse al ordenador/reductor. Una grabación inválida nunca avanza.
// ---------------------------------------------------------------------------
import type { Evento } from "../timeline/types.ts";
import { indiceEventoDeRuta, resumirErrores, validarGrabacion } from "./validar.ts";
import type { ErrorValidacion } from "./validar.ts";

// Una grabación ya validada (forma de recording.schema.json).
export interface Grabacion {
  readonly version: string;
  readonly descripcion: string;
  readonly run_id: string;
  readonly fuente_ref: string;
  readonly eventos: readonly Evento[];
}

// Error de carga con el detalle de validación y el seq del primer evento inválido.
export class ErrorGrabacion extends Error {
  readonly errores: readonly ErrorValidacion[];
  readonly seqInvalido: number | null;

  constructor(nombre: string, errores: readonly ErrorValidacion[], seqInvalido: number | null) {
    const donde = seqInvalido === null ? "" : ` (evento con seq ${seqInvalido})`;
    super(`La grabación "${nombre}" no cumple el contrato${donde}:\n${resumirErrores(errores)}`);
    this.name = "ErrorGrabacion";
    this.errores = errores;
    this.seqInvalido = seqInvalido;
  }
}

// Obtiene el seq del primer evento inválido, si los errores señalan uno.
function seqPrimerInvalido(dato: unknown, errores: readonly ErrorValidacion[]): number | null {
  const eventos = (dato as { eventos?: unknown })?.eventos;
  // Sin lista de eventos no hay a qué apuntar.
  if (!Array.isArray(eventos)) return null;
  for (const e of errores) {
    const indice = indiceEventoDeRuta(e.ruta);
    // Toma el primer error que apunte a un evento concreto.
    if (indice !== null) {
      const seq = (eventos[indice] as { seq?: unknown } | undefined)?.seq;
      return typeof seq === "number" ? seq : null;
    }
  }
  return null;
}

// Valida un dato crudo como grabación; lanza ErrorGrabacion si no cumple el contrato.
export function parsearGrabacion(nombre: string, dato: unknown): Grabacion {
  const resultado = validarGrabacion(dato);
  // Si el contrato no se cumple, se detiene el flujo con un error explícito.
  if (!resultado.ok) {
    throw new ErrorGrabacion(nombre, resultado.errores, seqPrimerInvalido(dato, resultado.errores));
  }
  return dato as Grabacion;
}

// JSON crudo de todas las grabaciones del repo, por ruta de archivo.
const crudas = import.meta.glob("../../../contracts/recordings/*.json", {
  eager: true,
  import: "default",
}) as Record<string, unknown>;

// Nombre corto de una grabación a partir de su ruta (sin carpeta ni extensión).
function nombreDeRuta(ruta: string): string {
  return ruta.replace(/^.*\//, "").replace(/\.json$/, "");
}

// Lista los nombres de grabación disponibles (excluye el esquema recording.schema).
export function listarGrabaciones(): string[] {
  return Object.keys(crudas)
    .filter((ruta) => !ruta.endsWith(".schema.json"))
    .map(nombreDeRuta)
    .sort();
}

// Carga y valida una grabación por nombre (p. ej. "b5_cifra_inventada").
export function cargarGrabacion(nombre: string): Grabacion {
  const ruta = Object.keys(crudas).find((r) => nombreDeRuta(r) === nombre);
  // Pedir una grabación que no existe es un error de uso, no de contrato.
  if (ruta === undefined) {
    throw new Error(`No existe la grabación "${nombre}". Disponibles: ${listarGrabaciones().join(", ")}`);
  }
  return parsearGrabacion(nombre, crudas[ruta]);
}