// ---------------------------------------------------------------------------
// validar.test.ts — Pruebas de la validación ajv y de la carga de grabaciones.
// Cubre: carga de los 19 esquemas, eventos válidos, mutaciones que deben rechazarse
// (una por regla del contrato) y todas las grabaciones reales de contracts/recordings.
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { ESQUEMAS } from "./esquemas.ts";
import { ErrorGrabacion, cargarGrabacion, listarGrabaciones, parsearGrabacion } from "./grabacion.ts";
import {
  crearValidador,
  indiceEventoDeRuta,
  resumirErrores,
  validarEvento,
} from "./validar.ts";

// --- Utilidades --------------------------------------------------------------

// Sobre común válido; cada prueba le suma lo propio del tipo.
const BASE = {
  version: "0.1",
  run_id: "run_demo",
  seq: 1,
  timestamp: "2026-11-13T12:00:02Z",
  origen: "grabado",
};

// Arma un evento mezclando el sobre base con los campos indicados.
function ev(extra: Record<string, unknown>): Record<string, unknown> {
  return { ...BASE, ...extra };
}

const SHA = "a".repeat(64);

// Eventos válidos mínimos, uno por situación relevante.
const FUENTE = ev({
  agente: "sistema",
  tipo: "fuente_indexada",
  payload: { num_fragmentos: 3, num_caracteres: 100, sha256: SHA },
});
const OPINION = ev({
  agente: "revisor",
  tipo: "verificacion_fidelidad",
  slide: 5,
  payload: {
    afirmacion_id: "a2",
    afirmacion: "Empieza hoy",
    clasificacion: "opinion_cta",
    veredicto: "no_aplica",
    cita: null,
    motivo: "Llamada a la acción.",
  },
});
const FONDO_IMAGEN = ev({
  agente: "director_arte",
  tipo: "colocar_fondo",
  slide: 2,
  payload: { fondo: { tipo: "imagen", referencia: "img_1", licencia: "CC0" } },
});
const APROBADA = ev({
  agente: "humano",
  tipo: "aprobada",
  payload: { decision: "aprobada", comentario: "Listo." },
});

// Verificación factual válida (base para varias mutaciones).
const FACTUAL = {
  afirmacion_id: "a1",
  afirmacion: "La Daily dura 15 minutos",
  clasificacion: "factual",
  veredicto: "respaldada",
  cita: { fragmento: "15 minutos", inicio: 10, fin: 20 },
  motivo: "Coincide.",
};

// --- Esquemas cargados -------------------------------------------------------
describe("esquemas del contrato", () => {
  it("se empaquetan los 19 esquemas con $id único", () => {
    expect(ESQUEMAS.length).toBeGreaterThanOrEqual(19);
    const ids = ESQUEMAS.map((e) => e.$id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("ajv compila todos los esquemas (con $ref entre archivos)", () => {
    expect(() => crearValidador(ESQUEMAS)).not.toThrow();
  });

  it("crearValidador falla de forma explícita si faltan esquemas", () => {
    expect(() => crearValidador([])).toThrow(/Faltan/);
  });
});

// --- Eventos válidos ---------------------------------------------------------
describe("validarEvento: casos válidos", () => {
  it.each([
    ["fuente_indexada", FUENTE],
    ["opinión/CTA con no_aplica y cita null", OPINION],
    ["fondo de imagen con licencia", FONDO_IMAGEN],
    ["aprobada con comentario opcional", APROBADA],
  ])("%s", (_nombre, evento) => {
    expect(validarEvento(evento)).toEqual({ ok: true });
  });
});

// --- Mutaciones que deben rechazarse ----------------------------------------
describe("validarEvento: mutaciones rechazadas", () => {
  const casos: [string, unknown][] = [
    ["seq 0", { ...FUENTE, seq: 0 }],
    ["tipo desconocido", { ...FUENTE, tipo: "evento_nuevo" }],
    ["payload sin campo requerido (sha256)", ev({ agente: "sistema", tipo: "fuente_indexada", payload: { num_fragmentos: 3, num_caracteres: 100 } })],
    ["agente que no corresponde al tipo", { ...FUENTE, agente: "redactor" }],
    ["propiedad extra en el payload", ev({ agente: "sistema", tipo: "fuente_indexada", payload: { num_fragmentos: 3, num_caracteres: 100, sha256: SHA, extra: 1 } })],
    ["propiedad extra en el sobre", { ...FUENTE, sorpresa: true }],
    ["run_id con formato inválido", { ...FUENTE, run_id: "RUN-1" }],
    ["versión fuera de 0.x", { ...FUENTE, version: "1.0" }],
    ["timestamp que no es fecha ISO", { ...FUENTE, timestamp: "ayer" }],
    ["sin payload", { ...FUENTE, payload: undefined }],
    ["slide fuera de rango (8)", ev({ agente: "director_arte", tipo: "escribir_texto", slide: 8, payload: { campo: "titulo", texto: "x" } })],
    ["escribir_texto sin slide", ev({ agente: "director_arte", tipo: "escribir_texto", payload: { campo: "titulo", texto: "x" } })],
    ["hallazgo_corregido sin causa", ev({ agente: "revisor", tipo: "hallazgo_corregido", slide: 3, payload: { hallazgo_id: "h1", resultado: "corregido", reevaluacion: "ok" } })],
    ["hallazgo_corregido con resultado fuera del enum", ev({ agente: "revisor", tipo: "hallazgo_corregido", slide: 3, causa: 2, payload: { hallazgo_id: "h1", resultado: "quizas", reevaluacion: "ok" } })],
    ["fondo de imagen sin licencia", ev({ agente: "director_arte", tipo: "colocar_fondo", slide: 2, payload: { fondo: { tipo: "imagen", referencia: "img_1" } } })],
    ["fondo de color con hex inválido", ev({ agente: "director_arte", tipo: "colocar_fondo", slide: 1, payload: { fondo: { tipo: "color", valor: "rojo" } } })],
    ["corregir con operación distinta de escribir_texto", ev({ agente: "redactor", tipo: "corregir", slide: 3, causa: 2, payload: { motivo: "m", operacion_nueva: { tipo: "borrar", campo: "titulo", texto: "x" } } })],
    ["corregir emitido por el revisor", ev({ agente: "revisor", tipo: "corregir", slide: 3, causa: 2, payload: { motivo: "m", operacion_nueva: { tipo: "escribir_texto", campo: "titulo", texto: "x" } } })],
    ["verificación: opinion_cta con veredicto distinto de no_aplica", ev({ agente: "revisor", tipo: "verificacion_fidelidad", slide: 5, payload: { ...FACTUAL, clasificacion: "opinion_cta" } })],
    ["verificación: respaldada con cita null", ev({ agente: "revisor", tipo: "verificacion_fidelidad", slide: 3, payload: { ...FACTUAL, cita: null } })],
    ["verificación: no_aplica con clasificación factual", ev({ agente: "revisor", tipo: "verificacion_fidelidad", slide: 3, payload: { ...FACTUAL, veredicto: "no_aplica" } })],
    ["verificación: contradice con opinion_cta", ev({ agente: "revisor", tipo: "verificacion_fidelidad", slide: 3, payload: { ...FACTUAL, clasificacion: "opinion_cta", veredicto: "contradice" } })],
    ["aprobada con decisión distinta de aprobada", ev({ agente: "humano", tipo: "aprobada", payload: { decision: "rechazada" } })],
  ];

  it.each(casos)("%s", (_nombre, evento) => {
    const r = validarEvento(evento);
    expect(r.ok).toBe(false);
    // Un rechazo siempre trae al menos un error explicable.
    if (!r.ok) expect(r.errores.length).toBeGreaterThan(0);
  });
});

// --- Utilidades de errores ---------------------------------------------------
describe("utilidades de errores", () => {
  it("indiceEventoDeRuta extrae el índice del evento", () => {
    expect(indiceEventoDeRuta("/eventos/3/payload/campo")).toBe(3);
    expect(indiceEventoDeRuta("/eventos/12")).toBe(12);
    expect(indiceEventoDeRuta("/run_id")).toBeNull();
    expect(indiceEventoDeRuta("/")).toBeNull();
  });

  it("resumirErrores recorta a un límite e indica cuántos quedan", () => {
    const errores = Array.from({ length: 8 }, (_, i) => ({ ruta: `/x/${i}`, mensaje: "mal" }));
    const texto = resumirErrores(errores, 3);
    expect(texto.split("\n")).toHaveLength(4);
    expect(texto).toContain("y 5 más");
  });
});

// --- Grabaciones reales ------------------------------------------------------
const nombres = listarGrabaciones();

describe.skipIf(nombres.length === 0)("grabaciones de contracts/recordings", () => {
  it("listarGrabaciones no incluye el esquema", () => {
    expect(nombres.every((n) => !n.includes("schema"))).toBe(true);
  });

  it.each(nombres)("%s pasa ajv, con seq consecutivos desde 1 y un solo run_id", (nombre) => {
    const g = cargarGrabacion(nombre);
    // Cada evento ocupa la posición que dice su seq (1, 2, 3, ...).
    g.eventos.forEach((e, i) => {
      expect(e.seq).toBe(i + 1);
      expect(e.run_id).toBe(g.run_id);
      expect(e.origen).toBe("grabado");
    });
  });

  it("una mutación dentro de la grabación detiene la carga y señala el seq", () => {
    const original = cargarGrabacion(nombres[0] as string);
    // Copia profunda para no tocar el original; el evento 3 queda con seq 0.
    const copia = JSON.parse(JSON.stringify(original)) as { eventos: { seq: number }[] };
    (copia.eventos[2] as { seq: number }).seq = 0;
    expect(() => parsearGrabacion("mutada", copia)).toThrow(ErrorGrabacion);
    try {
      parsearGrabacion("mutada", copia);
    } catch (e) {
      expect((e as ErrorGrabacion).seqInvalido).toBe(0);
      expect((e as ErrorGrabacion).message).toContain("mutada");
    }
  });

  it("pedir una grabación inexistente da un error claro", () => {
    expect(() => cargarGrabacion("no_existe")).toThrow(/No existe la grabación/);
  });
});

describe.skipIf(!nombres.includes("b5_cifra_inventada"))("b5_cifra_inventada", () => {
  it("trae los 22 eventos y todos pasan ajv", () => {
    const g = cargarGrabacion("b5_cifra_inventada");
    expect(g.eventos).toHaveLength(22);
    // Revalida cada evento por separado: es lo que hará el canal en vivo (SSE).
    for (const e of g.eventos) {
      expect(validarEvento(e)).toEqual({ ok: true });
    }
  });
});

// --- Grabación inválida en bloque -------------------------------------------
describe("parsearGrabacion", () => {
  it("rechaza un objeto que no es una grabación", () => {
    expect(() => parsearGrabacion("basura", { hola: 1 })).toThrow(ErrorGrabacion);
  });

  it("rechaza una grabación con menos de 2 eventos", () => {
    const g = { version: "0.1", descripcion: "Una descripción larga.", run_id: "run_demo", fuente_ref: "f.txt", eventos: [FUENTE] };
    expect(() => parsearGrabacion("corta", g)).toThrow(ErrorGrabacion);
  });
});