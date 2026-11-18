// ---------------------------------------------------------------------------
// fuenteEnVivo.test.ts — Pruebas de la fuente SSE con un EventSource falso:
// orden, idempotencia, huecos, evento inválido, cierre, pausa con acumulación,
// seek, reinicio y destrucción. El validador se inyecta para no depender del esquema.
// ---------------------------------------------------------------------------
import { describe, expect, it, vi } from "vitest";
import { MAX_REINTENTOS_HUECO, crearFuenteEnVivo } from "./fuenteEnVivo.ts";
import type { FuenteSse } from "./fuenteEnVivo.ts";
import type { Evento } from "./types.ts";

const RUN = "run_x";
const URL_BASE = "/api/runs/run_x/eventos";

// Valida todo: las pruebas que lo necesitan usan un validador que rechaza.
const aceptarTodo = (): { readonly ok: true } => ({ ok: true });

// Evento de prueba que escribe "t<seq>" en el campo titulo del slide 1.
function ev(seq: number): Evento {
  return {
    version: "0.1",
    run_id: RUN,
    seq,
    timestamp: "2026-11-11T20:00:00-03:00",
    origen: "grabado",
    agente: "director_arte",
    tipo: "escribir_texto",
    slide: 1,
    payload: { campo: "titulo", texto: `t${seq}` },
  };
}

// Evento run_finalizada de prueba (cierra el flujo).
function evFinal(seq: number): Evento {
  return {
    version: "0.1",
    run_id: RUN,
    seq,
    timestamp: "2026-11-11T20:00:00-03:00",
    origen: "grabado",
    agente: "sistema",
    tipo: "run_finalizada",
    payload: {
      estado_final: "aprobada",
      fact_ledger_ref: "x",
      sello: { afirmaciones_respaldadas: 0, afirmaciones_totales: 0 },
    },
  };
}

// EventSource falso: guarda oyentes y permite emitir mensajes a mano.
class FuenteFalsa implements FuenteSse {
  readyState = 0;
  cerrada = false;
  url: string;
  private oyentes = new Map<string, Array<(ev: MessageEvent) => void>>();

  constructor(url: string) {
    this.url = url;
  }

  addEventListener(tipo: string, oyente: (ev: MessageEvent) => void): void {
    this.oyentes.set(tipo, [...(this.oyentes.get(tipo) ?? []), oyente]);
  }

  close(): void {
    this.readyState = 2;
    this.cerrada = true;
  }

  // Dispara los oyentes de un tipo con un `data` (texto tal cual, o JSON si es un objeto).
  emitir(tipo: string, data?: unknown): void {
    const texto = data === undefined ? "" : typeof data === "string" ? data : JSON.stringify(data);
    const ev = { data: texto } as MessageEvent;
    // Un oyente por cada addEventListener del mismo tipo.
    for (const oyente of this.oyentes.get(tipo) ?? []) oyente(ev);
  }

  abrir(): void {
    this.readyState = 1;
    this.emitir("open");
  }

  mensaje(evento: Evento): void {
    this.emitir("message", evento);
  }
}

// Monta una fuente en vivo con fábrica falsa y devuelve acceso a las conexiones abiertas.
function montar(validar: (d: unknown) => ReturnType<typeof aceptarTodo> | { readonly ok: false; readonly errores: readonly { readonly ruta: string; readonly mensaje: string }[] } = aceptarTodo) {
  const fuentes: FuenteFalsa[] = [];
  const fuente = crearFuenteEnVivo(URL_BASE, {
    fabrica: (url) => {
      const f = new FuenteFalsa(url);
      fuentes.push(f);
      return f;
    },
    validar,
  });
  // Devuelve la conexión n-ésima (0 = la primera); falla si no existe.
  const conexion = (n: number): FuenteFalsa => {
    const f = fuentes[n];
    if (f === undefined) throw new Error(`No existe la conexión ${n}`);
    return f;
  };
  return { fuente, fuentes, conexion };
}

describe("fuenteEnVivo", () => {
  it("pasa a 'abierta' cuando la conexión abre", () => {
    const { fuente, conexion } = montar();
    expect(fuente.obtenerEnVivo().conexion).toBe("conectando");
    conexion(0).abrir();
    expect(fuente.obtenerEnVivo().conexion).toBe("abierta");
  });

  it("aplica los eventos en orden apenas llegan", () => {
    const { fuente, conexion } = montar();
    [1, 2, 3].forEach((n) => conexion(0).mensaje(ev(n)));
    const vista = fuente.obtener();
    expect(vista.total).toBe(3);
    expect(vista.aplicados).toBe(3);
    expect(vista.estado.ultimoSeq).toBe(3);
    expect(vista.estado.lienzo.textos[1]?.titulo).toBe("t3");
  });

  it("es idempotente: un seq repetido no se guarda dos veces", () => {
    const { fuente, conexion } = montar();
    [1, 2, 2, 1].forEach((n) => conexion(0).mensaje(ev(n)));
    expect(fuente.obtener().total).toBe(2);
  });

  it("ante un hueco reconecta con ?desde=<último seq> y sigue", () => {
    const { fuente, fuentes, conexion } = montar();
    conexion(0).mensaje(ev(1));
    conexion(0).mensaje(ev(3)); // falta el 2
    expect(fuentes).toHaveLength(2);
    expect(conexion(0).cerrada).toBe(true);
    expect(conexion(1).url).toBe(`${URL_BASE}?desde=1`);
    expect(fuente.obtenerEnVivo().conexion).toBe("reconectando");
    expect(fuente.obtener().total).toBe(1); // el 3 no se guardó

    conexion(1).abrir();
    conexion(1).mensaje(ev(2));
    conexion(1).mensaje(ev(3));
    expect(fuente.obtener().total).toBe(3);
    expect(fuente.obtenerEnVivo().conexion).toBe("abierta");
  });

  it("un hueco que persiste termina en error visible", () => {
    const { fuente, fuentes, conexion } = montar();
    conexion(0).mensaje(ev(1));
    // Cada intento emite de nuevo un seq 3 en la conexión más reciente.
    for (let i = 0; i <= MAX_REINTENTOS_HUECO; i++) {
      conexion(fuentes.length - 1).mensaje(ev(3));
    }
    expect(fuentes).toHaveLength(1 + MAX_REINTENTOS_HUECO);
    expect(fuente.obtenerEnVivo().conexion).toBe("error");
    expect(fuente.obtenerEnVivo().mensaje).toContain("Hueco persistente");
  });

  it("un evento que no cumple el contrato corta con error y no entra al buffer", () => {
    const { fuente, conexion } = montar(() => ({
      ok: false,
      errores: [{ ruta: "/seq", mensaje: "debe ser entero" }],
    }));
    conexion(0).mensaje(ev(1));
    expect(fuente.obtener().total).toBe(0);
    expect(fuente.obtenerEnVivo().conexion).toBe("error");
    expect(fuente.obtenerEnVivo().mensaje).toContain("/seq");
    expect(conexion(0).cerrada).toBe(true);
  });

  it("un mensaje que no es JSON es un error visible", () => {
    const { fuente, conexion } = montar();
    conexion(0).emitir("message", "esto no es json");
    expect(fuente.obtenerEnVivo().conexion).toBe("error");
  });

  it("el mensaje evento_invalido del servidor se muestra y corta", () => {
    const { fuente, conexion } = montar();
    conexion(0).mensaje(ev(1));
    conexion(0).emitir("evento_invalido", { seq: 5, tipo: "x", motivos: ["no cumple"] });
    expect(fuente.obtenerEnVivo().conexion).toBe("error");
    expect(fuente.obtenerEnVivo().mensaje).toContain("seq 5");
    expect(fuente.obtenerEnVivo().mensaje).toContain("no cumple");
    expect(conexion(0).cerrada).toBe(true);
  });

  it("run_finalizada cierra la conexión y marca terminado", () => {
    const { fuente, conexion } = montar();
    conexion(0).mensaje(ev(1));
    conexion(0).mensaje(evFinal(2));
    expect(conexion(0).cerrada).toBe(true);
    expect(fuente.obtenerEnVivo().conexion).toBe("cerrada");
    expect(fuente.obtener().terminado).toBe(true);
    expect(fuente.obtener().reproduciendo).toBe(false);
  });

  it("en pausa acumula en el buffer y al reproducir aplica todo de golpe", () => {
    const { fuente, conexion } = montar();
    fuente.pausar();
    [1, 2, 3].forEach((n) => conexion(0).mensaje(ev(n)));
    expect(fuente.obtener().total).toBe(3);
    expect(fuente.obtener().aplicados).toBe(0);
    expect(fuente.obtener().estado.ultimoSeq).toBe(0);

    fuente.reproducir();
    expect(fuente.obtener().aplicados).toBe(3);
    expect(fuente.obtener().estado.ultimoSeq).toBe(3);
  });

  it("irA reconstruye el estado, pausa si mira el pasado y valida el rango", () => {
    const { fuente, conexion } = montar();
    [1, 2, 3, 4].forEach((n) => conexion(0).mensaje(ev(n)));
    fuente.irA(2);
    expect(fuente.obtener().aplicados).toBe(2);
    expect(fuente.obtener().estado.lienzo.textos[1]?.titulo).toBe("t2");
    expect(fuente.obtener().reproduciendo).toBe(false);
    expect(() => fuente.irA(9)).toThrow(RangeError);
    expect(() => fuente.irA(-1)).toThrow(RangeError);
  });

  it("reiniciar cierra, vacía el buffer y reconecta desde cero reproduciendo", () => {
    const { fuente, fuentes, conexion } = montar();
    [1, 2].forEach((n) => conexion(0).mensaje(ev(n)));
    fuente.reiniciar();
    expect(conexion(0).cerrada).toBe(true);
    expect(fuentes).toHaveLength(2);
    expect(conexion(1).url).toBe(URL_BASE); // sin ?desde
    expect(fuente.obtener().total).toBe(0);
    expect(fuente.obtener().reproduciendo).toBe(true);
  });

  it("notifica a los oyentes y deja de hacerlo al darse de baja", () => {
    const { fuente, conexion } = montar();
    const oyente = vi.fn();
    const baja = fuente.suscribir(oyente);
    conexion(0).mensaje(ev(1));
    expect(oyente).toHaveBeenCalled();
    const llamadas = oyente.mock.calls.length;
    baja();
    conexion(0).mensaje(ev(2));
    expect(oyente).toHaveBeenCalledTimes(llamadas);
  });

  it("destruir cierra la conexión y silencia lo que llegue después", () => {
    const { fuente, conexion } = montar();
    const oyente = vi.fn();
    fuente.suscribir(oyente);
    fuente.destruir();
    expect(conexion(0).cerrada).toBe(true);
    conexion(0).mensaje(ev(1));
    expect(oyente).not.toHaveBeenCalled();
    expect(fuente.obtener().total).toBe(0);
  });

  it("rechaza una velocidad fuera de la lista", () => {
    const { fuente } = montar();
    // @ts-expect-error: 7 no es una Velocidad válida
    expect(() => fuente.velocidad(7)).toThrow(RangeError);
  });
});