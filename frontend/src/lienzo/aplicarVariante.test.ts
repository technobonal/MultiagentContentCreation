import { describe, expect, it } from "vitest";
import { aplicarVariante } from "./cargarPlantilla.ts";

const SVG = '<svg><style>:root { --acento:#3B49DF; }</style><rect fill="#bbdeff" stroke="#FFFFFF" clip-path="url(#recorte-foto-1)"/></svg>';

describe("aplicarVariante", () => {
  it("sin reemplazos deja la plantilla tal cual", () => {
    expect(aplicarVariante(SVG, undefined)).toBe(SVG);
    expect(aplicarVariante(SVG, {})).toBe(SVG);
  });

  it("cambia los colores en estilos y atributos, sin distinguir mayúsculas; el resto no se toca", () => {
    const pintado = aplicarVariante(SVG, { "#3B49DF": "#0B6B63", "#BBDEFF": "#C2F0DF" });
    expect(pintado).toContain("--acento:#0B6B63");
    expect(pintado).toContain('fill="#C2F0DF"');
    expect(pintado).toContain('stroke="#FFFFFF"');
    expect(pintado).toContain("url(#recorte-foto-1)");
  });

  it("no encadena: un color recién puesto no vuelve a reemplazarse", () => {
    expect(aplicarVariante("#111111 #222222", { "#111111": "#222222", "#222222": "#333333" })).toBe("#222222 #333333");
  });
});
