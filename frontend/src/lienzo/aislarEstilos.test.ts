// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { aislarEstilos, CLASE_PLANTILLA, parsearPlantilla } from "./cargarPlantilla.ts";

describe("aislarEstilos", () => {
  it("acota las variables de la plantilla a su propio SVG", () => {
    expect(aislarEstilos(":root { --fondo:#fff; }")).toBe(`.${CLASE_PLANTILLA} { --fondo:#fff; }`);
    expect(aislarEstilos(":root{--a:1}")).toBe(`.${CLASE_PLANTILLA}{--a:1}`);
  });

  it("no toca el resto del texto", () => {
    expect(aislarEstilos(".t { color:var(--texto); }")).toBe(".t { color:var(--texto); }");
  });

  it("acota todos los :root, también con saltos de línea como los de las plantillas", () => {
    const svg = "<style>\n  :root { --fondo:#BBDEFF; --texto:#101828; }\n  :root\n  { --acento:#3B49DF; }\n</style>";
    expect(aislarEstilos(svg)).not.toMatch(/:root\s*\{/);
    expect(aislarEstilos(svg).match(new RegExp(`\\.${CLASE_PLANTILLA}`, "g"))).toHaveLength(2);
  });

  it("el SVG montado lleva la clase a la que se acotan los estilos", () => {
    const raiz = parsearPlantilla('<svg xmlns="http://www.w3.org/2000/svg" class="otra"></svg>');
    expect(raiz.getAttribute("class")).toContain(CLASE_PLANTILLA);
    expect(raiz.getAttribute("class")).toContain("otra");
  });
});
