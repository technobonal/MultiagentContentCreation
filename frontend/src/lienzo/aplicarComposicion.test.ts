// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { aplicarComposicion, parsearPlantilla } from "./cargarPlantilla.ts";

const SVG =
  '<svg xmlns="http://www.w3.org/2000/svg"><clipPath id="recorte"><circle data-composicion="a" r="5"/>' +
  '<path data-composicion="b" d="M0 0Z"/></clipPath><g data-composicion="a" id="adorno-a"/>' +
  '<g data-composicion="b" id="adorno-b"><rect/></g><text id="comun">hola</text></svg>';

const formas = (texto: string) =>
  Array.from(parsearPlantilla(texto).querySelectorAll("*")).map((e) => e.getAttribute("id") ?? e.tagName);

describe("aplicarComposicion", () => {
  it("sin composición en el run deja la «a»", () => {
    expect(formas(aplicarComposicion(SVG))).toEqual(["recorte", "circle", "adorno-a", "comun"]);
  });

  it("deja solo la pedida, también dentro de un clipPath, y conserva lo común", () => {
    expect(formas(aplicarComposicion(SVG, "b"))).toEqual(["recorte", "path", "adorno-b", "rect", "comun"]);
  });

  it("una plantilla sin composiciones queda idéntica", () => {
    const simple = '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>';
    expect(aplicarComposicion(simple, "b")).toBe(simple);
  });
});
