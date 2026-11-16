import { describe, expect, it } from "vitest";
import { textoCampoCalculado } from "./camposCalculados.ts";
import { crearEstadoInicial } from "../timeline/reducer.ts";
import type { Estado, PayloadRunIniciada } from "../timeline/types.ts";

// Corrida de prueba con la fuente del caso estrella.
const run: PayloadRunIniciada = {
  entrada_ref: "entrada.json",
  plataforma: "instagram",
  idioma_salida: "es",
  num_slides: 6,
  verificacion: "verificada",
  fuente: {
    tipo: "documento",
    atribucion: "The Scrum Guide 2020 (Schwaber y Sutherland)",
    licencia: "CC BY-SA 4.0",
  },
};

// Estado de prueba con o sin corrida iniciada.
function estadoCon(conRun: boolean): Estado {
  return { ...crearEstadoInicial(), run: conRun ? run : null };
}

describe("textoCampoCalculado", () => {
  it("toma la atribución y la licencia de run_iniciada", () => {
    expect(textoCampoCalculado(estadoCon(true), "fuente_atribucion")).toBe(run.fuente.atribucion);
    expect(textoCampoCalculado(estadoCon(true), "fuente_licencia")).toBe("CC BY-SA 4.0");
  });

  it("devuelve undefined si la corrida todavía no empezó", () => {
    expect(textoCampoCalculado(estadoCon(false), "fuente_atribucion")).toBeUndefined();
    expect(textoCampoCalculado(estadoCon(false), "fuente_licencia")).toBeUndefined();
  });

  it("el sello es undefined mientras el ledger está vacío", () => {
    expect(textoCampoCalculado(estadoCon(true), "sello_revision")).toBeUndefined();
  });

  it("un campo que no es calculado devuelve undefined", () => {
    expect(textoCampoCalculado(estadoCon(true), "titulo")).toBeUndefined();
  });
});