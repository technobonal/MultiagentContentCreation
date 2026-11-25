// ---------------------------------------------------------------------------
// estadoAgentes.test.ts — Pruebas del texto de las fichas de la mesa de agentes:
// en espera, en curso y run terminado. Usa el reductor real para armar los estados.
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { crearEstadoInicial, reducirTodos } from "../timeline/reducer.ts";
import type { Evento } from "../timeline/types.ts";
import { ejecucionTerminada, textoEstadoAgente } from "./fase.ts";

// Arma un evento mínimo con el sobre común (el reductor solo mira estos campos).
function ev(seq: number, agente: string, tipo: string, payload: unknown, slide?: number): Evento {
  return {
    version: "0.1",
    run_id: "run_demo",
    seq,
    timestamp: "2026-11-22T10:00:00-03:00",
    origen: "real",
    agente,
    tipo,
    ...(slide !== undefined ? { slide } : {}),
    payload,
  } as unknown as Evento;
}

// Eventos 1..3: el run está en curso (estratega y redactor ya actuaron; el humano no).
const EN_CURSO: Evento[] = [
  ev(1, "sistema", "run_iniciada", {
    entrada_ref: "run_demo",
    plataforma: "instagram",
    idioma_salida: "es",
    num_slides: 6,
    verificacion: "verificada",
    fuente: { tipo: "documento", atribucion: "x", licencia: "CC-BY-SA-4.0" },
  }),
  ev(2, "estratega", "brief_emitido", {
    angulo: "a",
    tono: "t",
    num_slides: 6,
    tipo_mensaje: "lista_de_pasos",
    roles: ["gancho"],
  }),
  ev(3, "redactor", "texto_propuesto", { campo: "titulo", texto: "Hola" }, 1),
];

// Evento 4: el run termina (el ledger está vacío, así que el sello 0/0 es el calculado).
const FINAL: Evento = ev(4, "sistema", "run_finalizada", {
  estado_final: "aprobada",
  fact_ledger_ref: "x",
  sello: { afirmaciones_respaldadas: 0, afirmaciones_totales: 0 },
});

describe("textoEstadoAgente", () => {
  it("sin eventos todos los agentes están en espera", () => {
    const estado = crearEstadoInicial();
    expect(textoEstadoAgente(estado, "estratega", "es")).toBe("En espera");
    expect(textoEstadoAgente(estado, "humano", "pt-BR")).toBe("Em espera");
    expect(ejecucionTerminada(estado)).toBe(false);
  });

  it("con el run en curso muestra la última acción de cada agente", () => {
    const estado = reducirTodos(crearEstadoInicial(), EN_CURSO);
    expect(textoEstadoAgente(estado, "estratega", "es")).toBe("Planificando…");
    expect(textoEstadoAgente(estado, "redactor", "es")).toBe("Redactando…");
    expect(textoEstadoAgente(estado, "humano", "es")).toBe("En espera"); // aún no actuó
    expect(ejecucionTerminada(estado)).toBe(false);
  });

  it("con el run terminado, quien actuó figura como terminado y no queda ninguna acción vieja", () => {
    const estado = reducirTodos(crearEstadoInicial(), [...EN_CURSO, FINAL]);
    expect(ejecucionTerminada(estado)).toBe(true);
    expect(textoEstadoAgente(estado, "estratega", "es")).toBe("Terminado");
    expect(textoEstadoAgente(estado, "redactor", "es")).toBe("Terminado");
    expect(textoEstadoAgente(estado, "estratega", "pt-BR")).toBe("Concluído");
  });

  it("con el run terminado, quien nunca actuó ya no figura en espera", () => {
    const estado = reducirTodos(crearEstadoInicial(), [...EN_CURSO, FINAL]);
    expect(textoEstadoAgente(estado, "humano", "es")).toBe("Sin intervención");
    expect(textoEstadoAgente(estado, "humano", "pt-BR")).toBe("Sem intervenção");
  });

  it("al volver a un estado anterior al final (como irA), las fichas vuelven a su última acción", () => {
    const estado = reducirTodos(crearEstadoInicial(), EN_CURSO); // sin el evento final
    expect(ejecucionTerminada(estado)).toBe(false);
    expect(textoEstadoAgente(estado, "redactor", "es")).toBe("Redactando…");
  });
});