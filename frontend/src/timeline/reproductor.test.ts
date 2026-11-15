// ---------------------------------------------------------------------------
// reproductor.test.ts — Pruebas del reproductor (Paso 3, escritas antes que el código).
// Usan el reloj falso (tiempo controlado a mano) y, para simular un navegador lento,
// un reloj "tardío" cuyo temporizador llega con retraso. Si existe la grabación real
// b5_cifra_inventada, se corre además un bloque con ella.
// En la secuencia de prueba los eventos van cada 2 s: instantes 0, 2000, 4000...
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { cargarGrabacion, listarGrabaciones } from "../lib/grabacion.ts";
import { crearSecuencia } from "./eventosPrueba.ts";
import { crearEstadoInicial, reducirTodos } from "./reducer.ts";
import { crearRelojFalso } from "./reloj.ts";
import type { Reloj } from "./reloj.ts";
import { ErrorSecuencia, calcularInstantes, crearReproductor } from "./reproductor.ts";
import type { Reproductor, VistaReproductor } from "./reproductor.ts";
import type { Evento } from "./types.ts";

// --- Utilidades de prueba ----------------------------------------------------

// Copia del evento con otro timestamp (para armar brechas de tiempo a medida).
function conMarca(evento: Evento, marca: string): Evento {
  return { ...evento, timestamp: marca } as unknown as Evento;
}

// Atajo: cantidad de eventos aplicados según la vista actual.
function aplicados(r: Reproductor): number {
  return r.obtener().aplicados;
}

// Reloj que simula un navegador lento: el temporizador solo corre cuando la prueba
// lo dispara y puede llegar tarde (con varios eventos ya vencidos).
function crearRelojTardio(): { reloj: Reloj; dispararTarde: (ms: number) => void } {
  let instante = 0;
  let pendiente: (() => void) | null = null;
  const reloj: Reloj = {
    ahora: () => instante,
    programar: (_ms, callback) => {
      pendiente = callback;
      // Cancelar solo vale si el callback sigue siendo el pendiente.
      return () => {
        if (pendiente === callback) pendiente = null;
      };
    },
  };
  return {
    reloj,
    // Salta `ms` de tiempo y recién entonces dispara el temporizador pendiente.
    dispararTarde: (ms) => {
      instante += ms;
      const callback = pendiente;
      pendiente = null;
      if (callback !== null) callback();
    },
  };
}

// --- Creación ----------------------------------------------------------------
describe("crearReproductor: creación", () => {
  it("arranca en el estado inicial, en pausa, a 1x y sin eventos aplicados", () => {
    const r = crearReproductor(crearSecuencia(5), { reloj: crearRelojFalso() });
    const v = r.obtener();
    expect(v.aplicados).toBe(0);
    expect(v.total).toBe(5);
    expect(v.reproduciendo).toBe(false);
    expect(v.velocidad).toBe(1);
    expect(v.terminado).toBe(false);
    expect(v.estado).toEqual(crearEstadoInicial());
  });

  it("lanza ErrorSecuencia con los problemas si la secuencia no es reproducible", () => {
    // Falta el seq 3.
    const conHueco = crearSecuencia(5).filter((e) => e.seq !== 3);
    let error: unknown;
    try {
      crearReproductor(conHueco, { reloj: crearRelojFalso() });
    } catch (e) {
      error = e;
    }
    expect(error).toBeInstanceOf(ErrorSecuencia);
    expect((error as ErrorSecuencia).problemas.map((p) => p.codigo)).toEqual(["hueco"]);
  });

  it("ordena por seq una secuencia que llega desordenada", () => {
    const r = crearReproductor(crearSecuencia(5).reverse(), { reloj: crearRelojFalso() });
    r.irA(5);
    expect(r.obtener().estado).toEqual(reducirTodos(crearEstadoInicial(), crearSecuencia(5)));
  });

  it("rechaza un maxEsperaMs negativo", () => {
    expect(() =>
      crearReproductor(crearSecuencia(3), { reloj: crearRelojFalso(), maxEsperaMs: -1 }),
    ).toThrow(RangeError);
  });

  it("con una secuencia vacía, reproducir no hace nada", () => {
    const reloj = crearRelojFalso();
    const r = crearReproductor([], { reloj });
    r.reproducir();
    expect(r.obtener().total).toBe(0);
    expect(r.obtener().reproduciendo).toBe(false);
    expect(reloj.pendientes()).toBe(0);
  });
});

// --- Cálculo de instantes ------------------------------------------------------
describe("calcularInstantes", () => {
  it("acumula las brechas reales entre eventos (2 s en la secuencia de prueba)", () => {
    expect(calcularInstantes(crearSecuencia(5), 3000)).toEqual([0, 2000, 4000, 6000, 8000]);
    expect(calcularInstantes([], 3000)).toEqual([]);
  });

  it("recorta cada brecha al tope de espera", () => {
    const base = crearSecuencia(3);
    const [a, b, c] = base;
    // Brechas reales de 10 s y 2 s.
    const eventos = [
      conMarca(a as Evento, "2026-11-11T23:00:00.000Z"),
      conMarca(b as Evento, "2026-11-11T23:00:10.000Z"),
      conMarca(c as Evento, "2026-11-11T23:00:12.000Z"),
    ];
    // Con tope de 3 s la primera brecha se recorta; la segunda no.
    expect(calcularInstantes(eventos, 3000)).toEqual([0, 3000, 5000]);
    // Sin tope (Infinity) se respetan las brechas reales.
    expect(calcularInstantes(eventos, Number.POSITIVE_INFINITY)).toEqual([0, 10000, 12000]);
  });

  it("trata como 0 las brechas iguales, inválidas o negativas", () => {
    const marcas = [
      "2026-11-11T23:00:00.000Z", // 0
      "2026-11-11T23:00:02.000Z", // +2 s
      "2026-11-11T23:00:02.000Z", // misma marca: +0
      "no es una fecha", // inválida: +0
      "2026-11-11T23:00:10.000Z", // viene después de una inválida: +0
      "2026-11-11T23:00:12.000Z", // +2 s
      "2026-11-11T23:00:05.000Z", // retrocede: +0
    ];
    const base = crearSecuencia(7);
    // Cada evento recibe la marca que le toca por posición.
    const eventos = base.map((e, i) => conMarca(e, marcas[i] ?? ""));
    expect(calcularInstantes(eventos, 3000)).toEqual([0, 2000, 2000, 2000, 2000, 4000, 4000]);
  });
});

// --- Reproducción ---------------------------------------------------------------
describe("reproducir y pausar", () => {
  it("al reproducir aplica el primer evento de inmediato", () => {
    const reloj = crearRelojFalso();
    const eventos = crearSecuencia(5);
    const r = crearReproductor(eventos, { reloj });
    r.reproducir();
    expect(r.obtener().reproduciendo).toBe(true);
    expect(aplicados(r)).toBe(1);
    expect(r.obtener().estado).toEqual(reducirTodos(crearEstadoInicial(), eventos.slice(0, 1)));
    // Queda programado el siguiente evento.
    expect(reloj.pendientes()).toBe(1);
  });

  it("aplica cada evento cuando llega su instante", () => {
    const reloj = crearRelojFalso();
    const r = crearReproductor(crearSecuencia(5), { reloj });
    r.reproducir();
    reloj.avanzar(1999);
    // A 1 ms del segundo evento todavía no se aplica.
    expect(aplicados(r)).toBe(1);
    reloj.avanzar(1);
    expect(aplicados(r)).toBe(2);
    reloj.avanzar(2000);
    expect(aplicados(r)).toBe(3);
  });

  it("al llegar al final se detiene solo y no deja temporizadores", () => {
    const reloj = crearRelojFalso();
    const r = crearReproductor(crearSecuencia(5), { reloj });
    r.reproducir();
    reloj.avanzar(100000);
    const v = r.obtener();
    expect(v.aplicados).toBe(5);
    expect(v.terminado).toBe(true);
    expect(v.reproduciendo).toBe(false);
    expect(reloj.pendientes()).toBe(0);
  });

  it("el estado final coincide con aplicar todos los eventos con el reductor", () => {
    const reloj = crearRelojFalso();
    const eventos = crearSecuencia(8);
    const r = crearReproductor(eventos, { reloj });
    r.reproducir();
    reloj.avanzar(100000);
    expect(r.obtener().estado).toEqual(reducirTodos(crearEstadoInicial(), eventos));
  });

  it("reproducir dos veces seguidas no duplica temporizadores", () => {
    const reloj = crearRelojFalso();
    const r = crearReproductor(crearSecuencia(5), { reloj });
    r.reproducir();
    r.reproducir();
    expect(reloj.pendientes()).toBe(1);
    expect(aplicados(r)).toBe(1);
  });

  it("pausar congela el estado y cancela el temporizador", () => {
    const reloj = crearRelojFalso();
    const r = crearReproductor(crearSecuencia(5), { reloj });
    r.reproducir();
    reloj.avanzar(2500);
    expect(aplicados(r)).toBe(2);
    r.pausar();
    expect(r.obtener().reproduciendo).toBe(false);
    expect(reloj.pendientes()).toBe(0);
    // Pasa mucho tiempo en pausa: nada cambia.
    reloj.avanzar(10000);
    expect(aplicados(r)).toBe(2);
  });

  it("al reanudar continúa desde donde quedó, sin recuperar el tiempo en pausa", () => {
    const reloj = crearRelojFalso();
    const r = crearReproductor(crearSecuencia(5), { reloj });
    r.reproducir();
    reloj.avanzar(1000); // posición 1000: falta 1000 ms para el segundo evento
    r.pausar();
    reloj.avanzar(5000); // 5 s en pausa
    r.reproducir();
    reloj.avanzar(999);
    expect(aplicados(r)).toBe(1);
    reloj.avanzar(1);
    expect(aplicados(r)).toBe(2);
  });

  it("si el temporizador llega tarde, aplica de golpe todos los eventos vencidos con una sola notificación", () => {
    const { reloj, dispararTarde } = crearRelojTardio();
    const r = crearReproductor(crearSecuencia(5), { reloj });
    let notificaciones = 0;
    r.suscribir(() => {
      notificaciones += 1;
    });
    r.reproducir();
    expect(notificaciones).toBe(1);
    // El navegador despierta a los 5000 ms: ya vencieron los instantes 2000 y 4000.
    dispararTarde(5000);
    expect(aplicados(r)).toBe(3);
    expect(notificaciones).toBe(2);
    // Sin desfase acumulado: a los 6000 ms vence el cuarto evento.
    dispararTarde(1000);
    expect(aplicados(r)).toBe(4);
  });
});

// --- Velocidad -------------------------------------------------------------------
describe("velocidad", () => {
  it("a 2x los eventos llegan en la mitad del tiempo", () => {
    const reloj = crearRelojFalso();
    const r = crearReproductor(crearSecuencia(5), { reloj });
    r.velocidad(2);
    r.reproducir();
    expect(aplicados(r)).toBe(1);
    reloj.avanzar(1000);
    expect(aplicados(r)).toBe(2);
    reloj.avanzar(1000);
    expect(aplicados(r)).toBe(3);
  });

  it("cambiar la velocidad a mitad de reproducción re-ancla el tiempo", () => {
    const reloj = crearRelojFalso();
    const r = crearReproductor(crearSecuencia(5), { reloj });
    r.reproducir();
    reloj.avanzar(1000); // posición 1000 a 1x
    r.velocidad(2); // faltan 1000 ms de grabación = 500 ms reales
    reloj.avanzar(499);
    expect(aplicados(r)).toBe(1);
    reloj.avanzar(1);
    expect(aplicados(r)).toBe(2);
    // El tercer evento está 2000 ms de grabación más adelante = 1000 ms reales a 2x.
    reloj.avanzar(1000);
    expect(aplicados(r)).toBe(3);
  });

  it("rechaza velocidades que no sean 1 o 2", () => {
    const r = crearReproductor(crearSecuencia(3), { reloj: crearRelojFalso() });
    expect(() => r.velocidad(3 as never)).toThrow(RangeError);
  });
});

// --- Reiniciar -------------------------------------------------------------------
describe("reiniciar", () => {
  it("vuelve al inicio y queda en pausa, sin temporizadores", () => {
    const reloj = crearRelojFalso();
    const r = crearReproductor(crearSecuencia(5), { reloj });
    r.reproducir();
    reloj.avanzar(3000);
    expect(aplicados(r)).toBe(2);
    r.reiniciar();
    const v = r.obtener();
    expect(v.aplicados).toBe(0);
    expect(v.reproduciendo).toBe(false);
    expect(v.estado).toEqual(crearEstadoInicial());
    expect(reloj.pendientes()).toBe(0);
    // Aunque pase el tiempo, no arranca solo.
    reloj.avanzar(10000);
    expect(aplicados(r)).toBe(0);
  });

  it("reproducir después de terminar vuelve a empezar desde el principio", () => {
    const reloj = crearRelojFalso();
    const eventos = crearSecuencia(5);
    const r = crearReproductor(eventos, { reloj });
    r.reproducir();
    reloj.avanzar(100000);
    expect(r.obtener().terminado).toBe(true);
    r.reproducir();
    // Arrancó de nuevo: solo el primer evento aplicado.
    expect(aplicados(r)).toBe(1);
    expect(r.obtener().reproduciendo).toBe(true);
    reloj.avanzar(100000);
    expect(r.obtener().estado).toEqual(reducirTodos(crearEstadoInicial(), eventos));
  });
});

// --- Seek por índice ----------------------------------------------------------------
describe("irA", () => {
  it("para cada k deja el mismo estado que aplicar los primeros k eventos con el reductor", () => {
    const eventos = crearSecuencia(5);
    const r = crearReproductor(eventos, { reloj: crearRelojFalso() });
    // Se recorre de 0 a total con el mismo reproductor.
    for (let k = 0; k <= 5; k++) {
      r.irA(k);
      expect(aplicados(r)).toBe(k);
      expect(r.obtener().estado).toEqual(reducirTodos(crearEstadoInicial(), eventos.slice(0, k)));
    }
  });

  it("también funciona hacia atrás", () => {
    const eventos = crearSecuencia(5);
    const r = crearReproductor(eventos, { reloj: crearRelojFalso() });
    r.irA(5);
    r.irA(2);
    expect(aplicados(r)).toBe(2);
    expect(r.obtener().estado).toEqual(reducirTodos(crearEstadoInicial(), eventos.slice(0, 2)));
  });

  it("estando en pausa no arranca; al reproducir continúa desde ese punto", () => {
    const reloj = crearRelojFalso();
    const r = crearReproductor(crearSecuencia(5), { reloj });
    r.irA(2);
    expect(r.obtener().reproduciendo).toBe(false);
    r.reproducir();
    // Seguía el tercer evento (instante 4000) y la posición era 2000: faltan 2000 ms.
    expect(aplicados(r)).toBe(2);
    reloj.avanzar(1999);
    expect(aplicados(r)).toBe(2);
    reloj.avanzar(1);
    expect(aplicados(r)).toBe(3);
  });

  it("mientras reproduce, sigue reproduciendo desde el nuevo punto", () => {
    const reloj = crearRelojFalso();
    const r = crearReproductor(crearSecuencia(5), { reloj });
    r.reproducir();
    reloj.avanzar(500);
    r.irA(3);
    expect(aplicados(r)).toBe(3);
    expect(r.obtener().reproduciendo).toBe(true);
    // Posición 4000, el cuarto evento está en 6000: faltan 2000 ms.
    reloj.avanzar(1999);
    expect(aplicados(r)).toBe(3);
    reloj.avanzar(1);
    expect(aplicados(r)).toBe(4);
  });

  it("saltar al final termina la reproducción", () => {
    const reloj = crearRelojFalso();
    const r = crearReproductor(crearSecuencia(5), { reloj });
    r.reproducir();
    r.irA(5);
    const v = r.obtener();
    expect(v.terminado).toBe(true);
    expect(v.reproduciendo).toBe(false);
    expect(reloj.pendientes()).toBe(0);
  });

  it("rechaza índices fuera de rango o no enteros", () => {
    const r = crearReproductor(crearSecuencia(5), { reloj: crearRelojFalso() });
    expect(() => r.irA(-1)).toThrow(RangeError);
    expect(() => r.irA(6)).toThrow(RangeError);
    expect(() => r.irA(1.5)).toThrow(RangeError);
  });
});

// --- Suscripción -----------------------------------------------------------------------
describe("suscripción y vista", () => {
  it("notifica en cada cambio y deja de notificar al cancelar la suscripción", () => {
    const reloj = crearRelojFalso();
    const r = crearReproductor(crearSecuencia(5), { reloj });
    const vistos: number[] = [];
    const cancelar = r.suscribir((v) => vistos.push(v.aplicados));
    r.reproducir(); // 1 evento aplicado
    reloj.avanzar(2000); // 2 eventos aplicados
    cancelar();
    reloj.avanzar(2000); // 3 eventos, pero ya sin oyente
    expect(vistos).toEqual([1, 2]);
  });

  it("obtener() devuelve la misma referencia mientras nada cambia y una nueva tras un cambio", () => {
    const r = crearReproductor(crearSecuencia(5), { reloj: crearRelojFalso() });
    const inicial = r.obtener();
    // Ya estaba en pausa: pausar no cambia nada.
    r.pausar();
    expect(r.obtener()).toBe(inicial);
    r.reproducir();
    expect(r.obtener()).not.toBe(inicial);
  });

  it("destruir cancela los temporizadores y silencia a los oyentes", () => {
    const reloj = crearRelojFalso();
    const r = crearReproductor(crearSecuencia(5), { reloj });
    const vistas: VistaReproductor[] = [];
    r.suscribir((v) => vistas.push(v));
    r.reproducir();
    const antes = vistas.length;
    r.destruir();
    expect(reloj.pendientes()).toBe(0);
    reloj.avanzar(100000);
    // Después de destruir, ni el tiempo ni reproducir() producen cambios.
    r.reproducir();
    expect(vistas.length).toBe(antes);
    expect(aplicados(r)).toBe(1);
  });
});

// Solo se corre si la grabación real existe en contracts/recordings.
const hayGrabacion = listarGrabaciones().includes("b5_cifra_inventada");

describe.skipIf(!hayGrabacion)("reproductor con la grabación real b5_cifra_inventada", () => {
  it("reproducida de principio a fin da el mismo estado que el reductor", () => {
    const grabacion = cargarGrabacion("b5_cifra_inventada");
    const reloj = crearRelojFalso();
    const r = crearReproductor(grabacion.eventos, { reloj });
    r.reproducir();
    // 10 minutos de reloj falso: sobra para toda la grabación.
    reloj.avanzar(10 * 60 * 1000);
    const v = r.obtener();
    expect(v.terminado).toBe(true);
    expect(v.aplicados).toBe(22);
    expect(v.estado).toEqual(reducirTodos(crearEstadoInicial(), grabacion.eventos));
  });

  it("los instantes no decrecen y respetan el tope de 3 s por brecha", () => {
    const grabacion = cargarGrabacion("b5_cifra_inventada");
    const instantes = calcularInstantes(grabacion.eventos, 3000);
    expect(instantes).toHaveLength(22);
    expect(instantes.every((valor, i) => i === 0 || valor >= (instantes[i - 1] ?? 0))).toBe(true);
    // 21 brechas de, como máximo, 3000 ms.
    expect(instantes[instantes.length - 1] ?? 0).toBeLessThanOrEqual(21 * 3000);
  });
});