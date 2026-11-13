// ---------------------------------------------------------------------------
// validar.ts — Validación de eventos y grabaciones contra los esquemas del contrato.
// Usa ajv en modo 2020-12 + ajv-formats (para `format: "date-time"`).
// Los esquemas se registran por su $id, así los $ref relativos entre archivos resuelven.
// ---------------------------------------------------------------------------
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import type { ErrorObject, ValidateFunction } from "ajv/dist/2020.js";
import { ESQUEMAS, ID_ESQUEMA_EVENTO, ID_ESQUEMA_GRABACION } from "./esquemas.ts";
import type { EsquemaJson } from "./esquemas.ts";

// Un error de validación legible: dónde falló y por qué.
export interface ErrorValidacion {
  readonly ruta: string; // p. ej. "/payload/campo" o "/eventos/3/seq"
  readonly mensaje: string;
}

// Resultado de validar: éxito o lista de errores.
export type ResultadoValidacion =
  | { readonly ok: true }
  | { readonly ok: false; readonly errores: readonly ErrorValidacion[] };

// Validador con una función por contrato.
export interface Validador {
  readonly validarEvento: (dato: unknown) => ResultadoValidacion;
  readonly validarGrabacion: (dato: unknown) => ResultadoValidacion;
}

// Convierte los errores de ajv a nuestro formato y quita el ruido de if/then.
function aErrores(errores: readonly ErrorObject[] | null | undefined): ErrorValidacion[] {
  const lista = errores ?? [];
  // Las ramas "if/then" de event.schema.json generan un error resumen que no aporta.
  const utiles = lista.filter((e) => e.keyword !== "if");
  return utiles.map((e) => {
    // En additionalProperties, ajv indica en `params` cuál propiedad sobra: la mostramos.
    const sobrante =
      e.keyword === "additionalProperties" ? ` (${String(e.params.additionalProperty)})` : "";
    return {
      ruta: e.instancePath === "" ? "/" : e.instancePath,
      mensaje: `${e.message ?? "error de validación"}${sobrante}`,
    };
  });
}

// Envuelve una función compilada de ajv en nuestro ResultadoValidacion.
function envolver(fn: ValidateFunction): (dato: unknown) => ResultadoValidacion {
  return (dato) => {
    // ajv devuelve true si el dato cumple el esquema.
    if (fn(dato)) return { ok: true };
    return { ok: false, errores: aErrores(fn.errors) };
  };
}

// Crea un validador a partir de una lista de esquemas (inyectable para pruebas).
export function crearValidador(esquemas: readonly EsquemaJson[]): Validador {
  const ajv = new Ajv2020({
    allErrors: true, // reporta todos los errores, no solo el primero
    strict: true, // detecta typos en los esquemas
    strictTypes: false, // los bloques `then` usan `properties` sin `type`
    strictRequired: false, // cada payload exige `slide`/`causa`, definidos en el sobre
  });
  addFormats(ajv); // registra date-time y demás formatos
  // Registra cada esquema por su $id para que los $ref relativos se resuelvan.
  for (const esquema of esquemas) {
    ajv.addSchema(esquema);
  }
  const evento = ajv.getSchema(ID_ESQUEMA_EVENTO);
  const grabacion = ajv.getSchema(ID_ESQUEMA_GRABACION);
  // Sin estos dos esquemas no hay nada que validar: falla de forma explícita.
  if (!evento || !grabacion) {
    throw new Error("Faltan event.schema.json o recording.schema.json entre los esquemas cargados.");
  }
  return { validarEvento: envolver(evento), validarGrabacion: envolver(grabacion) };
}

// Validador listo para usar con los esquemas empaquetados (se crea la primera vez que se pide).
let instancia: Validador | null = null;
export function obtenerValidador(): Validador {
  instancia ??= crearValidador(ESQUEMAS);
  return instancia;
}

// Atajos sobre el validador compartido.
export const validarEvento = (dato: unknown): ResultadoValidacion =>
  obtenerValidador().validarEvento(dato);
export const validarGrabacion = (dato: unknown): ResultadoValidacion =>
  obtenerValidador().validarGrabacion(dato);

// Extrae el índice del evento de una ruta como "/eventos/3/payload" (o null si no aplica).
export function indiceEventoDeRuta(ruta: string): number | null {
  const m = /^\/eventos\/(\d+)(\/|$)/.exec(ruta);
  return m ? Number(m[1]) : null;
}

// Resume los errores en un texto corto para mostrar en un aviso (máx. `limite` líneas).
export function resumirErrores(errores: readonly ErrorValidacion[], limite = 5): string {
  const lineas = errores.slice(0, limite).map((e) => `${e.ruta}: ${e.mensaje}`);
  // Indica cuántos errores quedaron fuera del resumen.
  if (errores.length > limite) lineas.push(`… y ${errores.length - limite} más`);
  return lineas.join("\n");
}