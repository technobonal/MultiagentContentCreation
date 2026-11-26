import { describe, expect, it, vi } from "vitest";
import { crearCargadorDePlantillas } from "./cargarPlantilla.ts";

describe("crearCargadorDePlantillas", () => {
  it("descarga cada plantilla una sola vez", async () => {
    const cargar = vi.fn(async (id: string) => `<svg>${id}</svg>`);
    const cargador = crearCargadorDePlantillas(cargar);
    expect(await cargador("a")).toBe("<svg>a</svg>");
    expect(await cargador("a")).toBe("<svg>a</svg>");
    expect(await cargador("b")).toBe("<svg>b</svg>");
    expect(cargar.mock.calls.map((c) => c[0])).toEqual(["a", "b"]);
  });

  it("dos pedidos simultáneos comparten la misma descarga", async () => {
    const cargar = vi.fn(async () => "<svg/>");
    const cargador = crearCargadorDePlantillas(cargar);
    await Promise.all([cargador("a"), cargador("a")]);
    expect(cargar).toHaveBeenCalledTimes(1);
  });

  it("una carga que falla no se recuerda: se puede reintentar", async () => {
    const cargar = vi.fn().mockRejectedValueOnce(new Error("HTTP 404")).mockResolvedValue("<svg/>");
    const cargador = crearCargadorDePlantillas(cargar);
    await expect(cargador("a")).rejects.toThrow("HTTP 404");
    await expect(cargador("a")).resolves.toBe("<svg/>");
    expect(cargar).toHaveBeenCalledTimes(2);
  });
});
