import { describe, expect, it } from "vitest";
import { crearEstadoInicial } from "../timeline/reducer.ts";
import type { Estado } from "../timeline/types.ts";
import { puedeEstarEsperando, SILENCIO_MIN_SEG, textoEspera } from "./espera.ts";

function estado(cambios: Partial<Estado> = {}): Estado {
  return { ...crearEstadoInicial(), ...cambios };
}

describe("textoEspera", () => {
  it("no avisa con un silencio corto", () => {
    expect(textoEspera(0)).toBeNull();
    expect(textoEspera(SILENCIO_MIN_SEG - 0.1)).toBeNull();
  });
  it("avisa desde el mínimo y muestra los segundos enteros", () => {
    expect(textoEspera(SILENCIO_MIN_SEG)).toContain(`${SILENCIO_MIN_SEG} s`);
    expect(textoEspera(12.9)).toContain("12 s");
  });
});

describe("puedeEstarEsperando", () => {
  it("es falso antes del primer evento", () => {
    expect(puedeEstarEsperando(estado())).toBe(false);
  });
  it("es verdadero con el run abierto y sin cierre", () => {
    expect(puedeEstarEsperando(estado({ ultimoSeq: 5 }))).toBe(true);
  });
  it("es falso si el run terminó o espera a una persona", () => {
    expect(puedeEstarEsperando(estado({ ultimoSeq: 5, final: {} as Estado["final"] }))).toBe(false);
    const revision = {} as unknown as NonNullable<Estado["revision"]>;
    expect(puedeEstarEsperando(estado({ ultimoSeq: 5, revision }))).toBe(false);
  });
});
