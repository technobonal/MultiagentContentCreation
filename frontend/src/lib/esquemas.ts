// ---------------------------------------------------------------------------
// esquemas.ts — Carga los 19 JSON Schema del contrato, empaquetados en el bundle.
// Fuente única de verdad: contracts/ en la raíz del repo (no se copian ni se editan).
// En desarrollo, vite.config.ts debe permitir leer fuera de frontend (server.fs.allow).
// ---------------------------------------------------------------------------

// Esquema JSON genérico: lo único que exigimos es que tenga `$id`.
export interface EsquemaJson {
  readonly $id: string;
  readonly [clave: string]: unknown;
}

// Importa todos los *.schema.json de contracts/ en tiempo de build (eager = síncrono).
const modulos = import.meta.glob("../../../contracts/**/*.schema.json", {
  eager: true,
  import: "default",
}) as Record<string, EsquemaJson>;

// Lista de esquemas ordenada por ruta para que el orden de registro sea estable.
export const ESQUEMAS: readonly EsquemaJson[] = Object.keys(modulos)
  .sort()
  .map((ruta) => modulos[ruta] as EsquemaJson);

// $id del esquema que valida UN evento (el único que usan backend y frontend).
export const ID_ESQUEMA_EVENTO = "https://multiagent.local/contracts/events/event.schema.json";

// $id del esquema que valida una grabación completa.
export const ID_ESQUEMA_GRABACION =
  "https://multiagent.local/contracts/recordings/recording.schema.json";