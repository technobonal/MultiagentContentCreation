import { describe, expect, it, vi } from "vitest";
import { crearEstadoInicial } from "../timeline/reducer.ts";
import type { Estado } from "../timeline/types.ts";
import {
  camposEditables,
  camposModificados,
  claveCampo,
  cuerpoDecision,
  cuerpoRechazo,
  enviarAprobacion,
  RECHAZO_VACIO,
  esperaAprobacion,
  textoActual,
} from "./aprobacion.ts";

const REVISION = {
  estado_revision: "aprobada",
  hallazgos_abiertos: 0,
  sello: { afirmaciones_respaldadas: 4, afirmaciones_totales: 4 },
} as unknown as NonNullable<Estado["revision"]>;

/** Estado con dos slides dibujados; sin `revision` todavía. */
function estado(cambios: Partial<Estado> = {}): Estado {
  const base = crearEstadoInicial();
  return {
    ...base,
    lienzo: {
      ...base.lienzo,
      textos: { 2: { cuerpo: "Cuerpo 2" }, 1: { titulo: "Título 1", subtitulo: "Sub 1" } },
    },
    ...cambios,
  };
}

describe("esperaAprobacion", () => {
  it("es falso antes de pedir la aprobación", () => {
    expect(esperaAprobacion(estado())).toBe(false);
  });
  it("es verdadero tras aprobacion_solicitada y falso con decisión o cierre", () => {
    expect(esperaAprobacion(estado({ revision: REVISION }))).toBe(true);
    expect(esperaAprobacion(estado({ revision: REVISION, decision: { seq: 9 } }))).toBe(false);
    expect(esperaAprobacion(estado({ revision: REVISION, final: {} as Estado["final"] }))).toBe(false);
  });
});

describe("camposEditables", () => {
  it("ordena por slide y conserva el orden de los campos dentro del slide", () => {
    expect(camposEditables(estado()).map((c) => `${c.slide}:${c.campo}`)).toEqual(["1:titulo", "1:subtitulo", "2:cuerpo"]);
  });
  it("sin textos dibujados no hay nada que editar", () => {
    expect(camposEditables(crearEstadoInicial())).toEqual([]);
  });
});

describe("borradores y cuerpo de la decisión", () => {
  it("sin borradores no hay ediciones y el cuerpo no lleva comentario", () => {
    expect(cuerpoDecision(estado(), {}, "   ")).toEqual({ ediciones: [] });
  });

  it("solo viajan los campos que cambiaron, con el texto limpio", () => {
    const borradores = {
      [claveCampo(1, "titulo")]: "  Nuevo título  ",
      [claveCampo(1, "subtitulo")]: "Sub 1", // igual al dibujado: no es una edición
      [claveCampo(2, "cuerpo")]: "Cuerpo 2 ", // solo cambian los espacios: tampoco
    };
    expect(cuerpoDecision(estado(), borradores, " Ok. ")).toEqual({
      ediciones: [{ slide: 1, campo: "titulo", texto: "Nuevo título" }],
      comentario: "Ok.",
    });
  });

  it("un borrador vacío cuenta como modificado: el servidor lo rechaza con su motivo", () => {
    const borradores = { [claveCampo(1, "titulo")]: "   " };
    expect(camposModificados(estado(), borradores).map((c) => c.campo)).toEqual(["titulo"]);
  });

  it("textoActual prefiere el borrador y si no, lo dibujado", () => {
    const [titulo] = camposEditables(estado());
    expect(textoActual({}, titulo!)).toBe("Título 1");
    expect(textoActual({ [claveCampo(1, "titulo")]: "Otro" }, titulo!)).toBe("Otro");
  });
});

function respuesta(status: number, cuerpo?: unknown): Response {
  return new Response(cuerpo === undefined ? null : JSON.stringify(cuerpo), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("enviarAprobacion", () => {
  it("envía un POST JSON al endpoint del run (con el id escapado)", async () => {
    const llamar = vi.fn().mockResolvedValue(respuesta(202, { run_id: "run_x", ediciones: 1 }));
    const r = await enviarAprobacion("run x", { ediciones: [], comentario: "Ok" }, llamar);
    expect(r).toEqual({ ok: true, ediciones: 1 });
    const [url, init] = llamar.mock.calls[0]!;
    expect(url).toBe("/api/runs/run%20x/aprobacion");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ ediciones: [], comentario: "Ok" });
  });

  it("422 y 409 devuelven los motivos del servidor", async () => {
    const motivos = ["Edición 1: supera 20 caracteres (21).", "otro"];
    expect(await enviarAprobacion("r", { ediciones: [] }, vi.fn().mockResolvedValue(respuesta(422, { motivos }))))
      .toEqual({ ok: false, motivos });
    expect(await enviarAprobacion("r", { ediciones: [] }, vi.fn().mockResolvedValue(respuesta(409, { motivos: ["Ya decidió."] }))))
      .toEqual({ ok: false, motivos: ["Ya decidió."] });
  });

  it("404 usa el detalle y una respuesta sin JSON usa el código", async () => {
    expect(await enviarAprobacion("r", { ediciones: [] }, vi.fn().mockResolvedValue(respuesta(404, { detail: "No existe la ejecución r" }))))
      .toEqual({ ok: false, motivos: ["No existe la ejecución r"] });
    expect(await enviarAprobacion("r", { ediciones: [] }, vi.fn().mockResolvedValue(new Response("boom", { status: 502 }))))
      .toEqual({ ok: false, motivos: ["El servidor respondió 502."] });
  });

  it("si no hay conexión no lanza: devuelve un motivo", async () => {
    const r = await enviarAprobacion("r", { ediciones: [] }, vi.fn().mockRejectedValue(new TypeError("fallo de red")));
    expect(r).toEqual({ ok: false, motivos: ["No se pudo conectar con el servidor."] });
  });
});

describe("cuerpoRechazo", () => {
  it("con solo el motivo no envía nada más, y lo recorta", () => {
    expect(cuerpoRechazo({ ...RECHAZO_VACIO, motivo: "  Cambia la fuente  ", esperado: "   " })).toEqual({
      rechazo: { motivo: "Cambia la fuente" },
    });
  });
  it("envía quién falló, el slide y lo esperado cuando se indican", () => {
    expect(cuerpoRechazo({ motivo: "m", responsable: "revisor", slide: 3, esperado: " e " })).toEqual({
      rechazo: { motivo: "m", responsable: "revisor", slide: 3, esperado: "e" },
    });
  });
  it("se envía al mismo endpoint que la aprobación", async () => {
    const llamar = vi.fn(async () => new Response(JSON.stringify({ ediciones: 0 }), { status: 202 }));
    await expect(enviarAprobacion("run_1", { rechazo: { motivo: "m" } }, llamar)).resolves.toEqual({ ok: true, ediciones: 0 });
    expect(llamar).toHaveBeenCalledWith("/api/runs/run_1/aprobacion", expect.objectContaining({
      method: "POST", body: JSON.stringify({ rechazo: { motivo: "m" } }),
    }));
  });
});
