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
  motivoDemasiadoGeneral,
  RECHAZO_VACIO,
  esperaAprobacion,
  motivosSinHallazgo,
  necesitaExcepcion,
  pedirConsejo,
  pedirInforme,
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

describe("motivoDemasiadoGeneral", () => {
  it("marca motivos vagos o muy cortos", () => {
    expect(motivoDemasiadoGeneral("no me gusta")).toBe(true);
    expect(motivoDemasiadoGeneral("está mal")).toBe(true);
    expect(motivoDemasiadoGeneral("feo")).toBe(true);
  });
  it("acepta un motivo concreto y no pregunta con el campo vacío", () => {
    expect(motivoDemasiadoGeneral("El slide 3 inventa una cifra que no está en la fuente")).toBe(false);
    expect(motivoDemasiadoGeneral("   ")).toBe(false);
  });
});

describe("semáforo y excepción", () => {
  const VERDE = { visto_bueno: true, generales: [], slides: [{ slide: 1, color: "verde", motivos: [], avisos: [] }] } as const;

  it("hace falta excepción en rojo o con ediciones, aunque el servidor diera verde", () => {
    expect(necesitaExcepcion(VERDE, 0)).toBe(false);
    expect(necesitaExcepcion(VERDE, 1)).toBe(true);
    expect(necesitaExcepcion({ ...VERDE, visto_bueno: false }, 0)).toBe(true);
  });

  it("la excepción viaja solo si tiene texto", () => {
    expect(cuerpoDecision(estado(), {}, "", "  ")).toEqual({ ediciones: [] });
    expect(cuerpoDecision(estado(), {}, "", " Lo comprobé. ")).toEqual({ ediciones: [], excepcion: "Lo comprobé." });
  });

  it("pide el informe del run", async () => {
    const llamar = vi.fn(async () => new Response(JSON.stringify(VERDE)));
    await expect(pedirInforme("run_1", llamar)).resolves.toEqual(VERDE);
    expect(llamar).toHaveBeenCalledWith("/api/runs/run_1/informe");
  });

  it.each([
    ["un 404", async () => new Response("{}", { status: 404 })],
    ["una forma inesperada", async () => new Response(JSON.stringify({ visto_bueno: "sí" }))],
    ["sin conexión", async () => Promise.reject(new Error("red"))],
  ])("con %s no inventa un informe", async (_, llamar) => {
    await expect(pedirInforme("run_1", llamar as typeof fetch)).resolves.toBeNull();
  });

  it("pedirConsejo hace POST y devuelve el informe actualizado", async () => {
    const llamar = vi.fn(async () => new Response(JSON.stringify(VERDE), { status: 200 }));
    await expect(pedirConsejo("run_1", llamar)).resolves.toEqual({ ok: true, informe: VERDE });
    expect(llamar).toHaveBeenCalledWith("/api/runs/run_1/asesor", { method: "POST" });
  });

  it("pedirConsejo devuelve los motivos del servidor (409, 503) y nunca lanza", async () => {
    expect(await pedirConsejo("r", vi.fn(async () => new Response(JSON.stringify({ motivos: ["Ya usaste las 3 consultas."] }), { status: 409 }))))
      .toEqual({ ok: false, motivos: ["Ya usaste las 3 consultas."] });
    expect(await pedirConsejo("r", vi.fn(async () => Promise.reject(new Error("red"))) as unknown as typeof fetch))
      .toEqual({ ok: false, motivos: ["No se pudo conectar con el asesor."] });
  });
});

describe("motivosSinHallazgo", () => {
  const informe = {
    visto_bueno: false, generales: [],
    slides: [{ slide: 3, color: "rojo" as const, avisos: [], motivos: ["Hallazgo h1 (mayor): x", "Su texto actual no tiene ningún veredicto del revisor.", "Alerta del asesor: «y»"] }],
  };
  it("deja lo que el revisor no abrió como hallazgo, y nada si el slide no está", () => {
    expect(motivosSinHallazgo(informe, 3)).toEqual(["Su texto actual no tiene ningún veredicto del revisor.", "Alerta del asesor: «y»"]);
    expect(motivosSinHallazgo(informe, 4)).toEqual([]);
  });
});
