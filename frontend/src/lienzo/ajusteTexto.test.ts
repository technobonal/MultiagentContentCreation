import { describe, expect, it } from "vitest";
import { ajustarTexto, type Medidor } from "./ajusteTexto";

// Medidor falso: cada carácter ocupa 0,55 × la fuente y la caja mide 920 px de ancho.
const medidorFalso: Medidor = (texto, fuentePx) => {
  const porLinea = Math.floor(920 / (fuentePx * 0.55));
  return Math.max(1, Math.ceil(texto.length / porLinea));
};

// Título de la plantilla de pasos: 64 px, line-height 74, mínimo 56, máximo 3 líneas.
const titulo = {
  fuenteBase: 64,
  lineHeightBase: 74,
  fuenteMin: 56,
  lineasMax: 3,
};

describe("ajustarTexto", () => {
  it("cabe a la primera: estado ok y tamaño base", () => {
    const r = ajustarTexto({ ...titulo, texto: "a".repeat(20) }, medidorFalso);
    expect(r).toMatchObject({ estado: "ok", fuentePx: 64, lineHeightPx: 74, lineas: 1 });
  });

  it("cabe tras encoger: baja de 2 en 2 y escala el line-height", () => {
    // 80 caracteres: 4 líneas a 64 y 62 px, 3 líneas a 60 px.
    const r = ajustarTexto({ ...titulo, texto: "a".repeat(80) }, medidorFalso);
    expect(r.estado).toBe("encogido");
    expect(r.fuentePx).toBe(60);
    expect(r.lineHeightPx).toBe(69); // round(74 × 60 / 64)
  });

  it("desborda en el mínimo: no recorta y reporta el tamaño mínimo", () => {
    const r = ajustarTexto({ ...titulo, texto: "a".repeat(400) }, medidorFalso);
    expect(r.estado).toBe("desborda");
    expect(r.fuentePx).toBe(56);
    expect(r.lineas).toBeGreaterThan(3);
  });

  it("el último paso se ajusta al mínimo aunque no sea múltiplo del paso", () => {
    // Nunca cabe: se registran todos los tamaños medidos.
    const visitados: number[] = [];
    const nuncaCabe: Medidor = (_t, fuente) => {
      visitados.push(fuente);
      return 99;
    };
    const r = ajustarTexto(
      { ...titulo, fuenteMin: 57, texto: "x" },
      nuncaCabe,
    );
    expect(visitados).toEqual([64, 62, 60, 58, 57]);
    expect(r.estado).toBe("desborda");
  });

  it("si la base ya es menor que el mínimo, mide una sola vez", () => {
    let medidas = 0;
    const contador: Medidor = () => {
      medidas += 1;
      return 99;
    };
    const r = ajustarTexto(
      { ...titulo, fuenteBase: 24, lineHeightBase: 40, fuenteMin: 30, texto: "x" },
      contador,
    );
    expect(medidas).toBe(1);
    expect(r.estado).toBe("desborda");
  });

  it("un paso inválido usa el valor por defecto y no cuelga", () => {
    const r = ajustarTexto(
      { ...titulo, paso: 0, texto: "a".repeat(400) },
      medidorFalso,
    );
    expect(r.estado).toBe("desborda");
  });

  it("rechaza una fuente base no positiva", () => {
    expect(() =>
      ajustarTexto({ ...titulo, fuenteBase: 0, texto: "x" }, medidorFalso),
    ).toThrow();
  });
});