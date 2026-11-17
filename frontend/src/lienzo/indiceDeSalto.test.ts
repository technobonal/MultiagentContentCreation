// ---------------------------------------------------------------------------
// indiceDeSalto.test.ts — Pruebas de la lógica pura de las miniaturas.
// Usan una secuencia sintética corta: slide 1 con fondo y título, slide 3 con una
// verificación (que NO da contenido), un borrador y el texto dibujado.
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { crearEstadoInicial, reducirTodos } from "../timeline/reducer.ts";
import type { Evento } from "../timeline/types.ts";
import { indiceDeSalto, slideTieneContenido } from "./indiceDeSalto.ts";

// Crea un evento completo (sobre común + payload) de forma compacta.
function ev(seq: number, agente: string, tipo: string, slide: number | undefined, payload: unknown): Evento {
  return {
    version: "0.1",
    run_id: "run_demo",
    seq,
    timestamp: `2026-11-13T12:00:${String(seq).padStart(2, "0")}Z`,
    origen: "grabado",
    agente,
    tipo,
    // El slide es opcional: solo se incluye si se da.
    ...(slide !== undefined ? { slide } : {}),
    payload,
  } as unknown as Evento;
}

// Secuencia de prueba (5 eventos).
const SECUENCIA: Evento[] = [
  ev(1, "director_arte", "colocar_fondo", 1, { fondo: { tipo: "color", valor: "#112233" } }),
  ev(2, "director_arte", "escribir_texto", 1, { campo: "titulo", texto: "Hola" }),
  ev(3, "revisor", "verificacion_fidelidad", 3, {
    afirmacion_id: "a1",
    afirmacion: "x",
    clasificacion: "factual",
    veredicto: "respaldada",
    cita: null,
    motivo: "m",
  }),
  ev(4, "redactor", "texto_propuesto", 3, { campo: "cuerpo", texto: "borrador" }),
  ev(5, "director_arte", "escribir_texto", 3, { campo: "cuerpo", texto: "final" }),
];

describe("indiceDeSalto", () => {
  it("devuelve el índice del primer evento que da contenido al slide", () => {
    // El fondo del slide 1 es el primer evento: se aplica 1 evento.
    expect(indiceDeSalto(SECUENCIA, 1)).toBe(1);
  });

  it("ignora los eventos que no dibujan (la verificación del revisor)", () => {
    // El evento 3 es del slide 3 pero no da contenido; el primero que sí es el 4.
    expect(indiceDeSalto(SECUENCIA, 3)).toBe(4);
  });

  it("devuelve null si ningún evento da contenido al slide", () => {
    expect(indiceDeSalto(SECUENCIA, 2)).toBeNull();
    expect(indiceDeSalto([], 1)).toBeNull();
  });

  it("no depende del orden en que llegan los eventos", () => {
    const desordenada = [...SECUENCIA].reverse();
    expect(indiceDeSalto(desordenada, 3)).toBe(4);
  });
});

describe("slideTieneContenido", () => {
  it("el estado inicial no tiene contenido en ningún slide", () => {
    expect(slideTieneContenido(crearEstadoInicial(), 1)).toBe(false);
  });

  it("reconoce texto dibujado, fondo y borrador", () => {
    const base = crearEstadoInicial();
    expect(slideTieneContenido({ ...base, lienzo: { ...base.lienzo, textos: { 2: { titulo: "x" } } } }, 2)).toBe(true);
    expect(
      slideTieneContenido(
        { ...base, lienzo: { ...base.lienzo, fondos: { 4: { tipo: "color", valor: "#000" } } } },
        4,
      ),
    ).toBe(true);
    expect(slideTieneContenido({ ...base, propuestas: { 5: { cuerpo: "b" } } }, 5)).toBe(true);
  });
});

describe("coherencia con el reductor", () => {
  // Invariante: con k eventos el slide tiene contenido; con k - 1 todavía no.
  it.each([1, 3])("el slide %i tiene contenido justo desde su índice de salto", (slide) => {
    const k = indiceDeSalto(SECUENCIA, slide);
    expect(k).not.toBeNull();
    const salto = k ?? 0;
    // Con k eventos aplicados ya hay contenido.
    expect(slideTieneContenido(reducirTodos(crearEstadoInicial(), SECUENCIA.slice(0, salto)), slide)).toBe(true);
    // Con un evento menos todavía no.
    expect(slideTieneContenido(reducirTodos(crearEstadoInicial(), SECUENCIA.slice(0, salto - 1)), slide)).toBe(false);
  });
});