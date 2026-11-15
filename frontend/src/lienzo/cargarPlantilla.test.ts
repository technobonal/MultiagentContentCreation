import { describe, expect, it } from "vitest";
import { reescribirRutasDeFuentes } from "./cargarPlantilla.ts";

// Fragmento con las dos fuentes de la plantilla, tal como aparecen en el SVG.
const css = `
  src: url("../../typography/inter/Inter-Variable.ttf") format("truetype");
  src: url("../../typography/jetbrains-mono/JetBrainsMono-Regular.ttf") format("truetype");
`;

describe("reescribirRutasDeFuentes", () => {
  it("reemplaza las dos rutas relativas por rutas desde la base", () => {
    const r = reescribirRutasDeFuentes(css, "/");
    expect(r).toContain('url("/plantillas/typography/inter/Inter-Variable.ttf")');
    expect(r).toContain('url("/plantillas/typography/jetbrains-mono/JetBrainsMono-Regular.ttf")');
    expect(r).not.toContain("../../typography/");
  });

  it("agrega la barra final cuando la base no la trae", () => {
    expect(reescribirRutasDeFuentes(css, "/app")).toContain(
      'url("/app/plantillas/typography/inter/Inter-Variable.ttf")',
    );
  });

  it("deja el texto igual si no hay rutas que reescribir", () => {
    expect(reescribirRutasDeFuentes("<svg/>", "/")).toBe("<svg/>");
  });
});