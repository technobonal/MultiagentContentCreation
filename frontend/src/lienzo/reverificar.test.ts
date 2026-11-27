import { describe, expect, it, vi } from "vitest";
import { crearEstadoInicial } from "../timeline/reducer.ts";
import type { Estado } from "../timeline/types.ts";
import { claveCampo } from "./aprobacion.ts";
import { cambiosDelSlide, cuerpoEdicion, pedirReverificacion } from "./reverificar.ts";

/** Estado con dos slides dibujados (slide 1: titulo y subtitulo; slide 2: cuerpo). */
function estado(): Estado {
  const base = crearEstadoInicial();
  return {
    ...base,
    lienzo: { ...base.lienzo, textos: { 1: { titulo: "Título 1", subtitulo: "Sub 1" }, 2: { cuerpo: "Cuerpo 2" } } },
  };
}

describe("cuerpoEdicion y cambiosDelSlide", () => {
  it("solo toma los campos cambiados de ESE slide, con el texto limpio", () => {
    const borradores = {
      [claveCampo(1, "titulo")]: "  Nuevo título  ",
      [claveCampo(1, "subtitulo")]: "Sub 1", // igual: no cuenta
      [claveCampo(2, "cuerpo")]: "Otro cuerpo", // otro slide: no entra
    };
    expect(cambiosDelSlide(estado(), borradores, 1)).toBe(1);
    expect(cuerpoEdicion(estado(), borradores, 1)).toEqual({
      slide: 1,
      modo: "edicion",
      ediciones: [{ slide: 1, campo: "titulo", texto: "Nuevo título" }],
    });
  });

  it("sin cambios, la lista de ediciones queda vacía", () => {
    expect(cambiosDelSlide(estado(), {}, 1)).toBe(0);
    expect(cuerpoEdicion(estado(), {}, 1)).toEqual({ slide: 1, modo: "edicion", ediciones: [] });
  });
});

describe("pedirReverificacion", () => {
  it("hace POST con el cuerpo y, en 202, devuelve ok", async () => {
    const llamar = vi.fn().mockResolvedValue(new Response(JSON.stringify({ run_id: "r", slide: 1, modo: "agente" }), { status: 202 }));
    await expect(pedirReverificacion("run 1", { slide: 1, modo: "agente" }, llamar)).resolves.toEqual({ ok: true });
    const [url, init] = llamar.mock.calls[0]!;
    expect(url).toBe("/api/runs/run%201/reverificar");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ slide: 1, modo: "agente" });
  });

  it("devuelve los motivos del servidor (409/422) y nunca lanza", async () => {
    expect(await pedirReverificacion("r", { slide: 1, modo: "agente" }, vi.fn(async () => new Response(JSON.stringify({ motivos: ["Ya usaste las 3 re-verificaciones de este run."] }), { status: 409 }))))
      .toEqual({ ok: false, motivos: ["Ya usaste las 3 re-verificaciones de este run."] });
    expect(await pedirReverificacion("r", { slide: 1, modo: "agente" }, vi.fn(async () => Promise.reject(new Error("red"))) as unknown as typeof fetch))
      .toEqual({ ok: false, motivos: ["No se pudo conectar con el servidor."] });
  });
});
