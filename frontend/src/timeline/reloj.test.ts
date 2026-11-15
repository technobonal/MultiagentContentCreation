// ---------------------------------------------------------------------------
// reloj.test.ts — Pruebas del reloj inyectable (Paso 3, escritas antes que el código).
// Cubre el reloj falso (control manual del tiempo) y el reloj real (con los
// temporizadores falsos de Vitest, sin esperas reales).
// ---------------------------------------------------------------------------
import { describe, expect, it, vi } from "vitest";
import { crearRelojFalso, relojReal } from "./reloj.ts";

describe("crearRelojFalso", () => {
  it("empieza en 0 o en el instante indicado", () => {
    expect(crearRelojFalso().ahora()).toBe(0);
    expect(crearRelojFalso(500).ahora()).toBe(500);
  });

  it("avanzar mueve el instante actual", () => {
    const reloj = crearRelojFalso();
    reloj.avanzar(250);
    reloj.avanzar(50);
    expect(reloj.ahora()).toBe(300);
  });

  it("no dispara antes de vencer y sí exactamente al vencer", () => {
    const reloj = crearRelojFalso();
    const llamadas: string[] = [];
    reloj.programar(100, () => llamadas.push("x"));
    reloj.avanzar(99);
    // A 1 ms del vencimiento todavía no corre.
    expect(llamadas).toEqual([]);
    reloj.avanzar(1);
    expect(llamadas).toEqual(["x"]);
  });

  it("dispara en orden de vencimiento, no de programación", () => {
    const reloj = crearRelojFalso();
    const llamadas: number[] = [];
    // Se programan desordenados: 30, 10, 20.
    reloj.programar(30, () => llamadas.push(30));
    reloj.programar(10, () => llamadas.push(10));
    reloj.programar(20, () => llamadas.push(20));
    reloj.avanzar(100);
    expect(llamadas).toEqual([10, 20, 30]);
  });

  it("con el mismo vencimiento respeta el orden de programación", () => {
    const reloj = crearRelojFalso();
    const llamadas: string[] = [];
    reloj.programar(10, () => llamadas.push("a"));
    reloj.programar(10, () => llamadas.push("b"));
    reloj.programar(10, () => llamadas.push("c"));
    reloj.avanzar(10);
    expect(llamadas).toEqual(["a", "b", "c"]);
  });

  it("dentro de un callback, ahora() vale su instante de vencimiento y no el final del avance", () => {
    const reloj = crearRelojFalso();
    const vistos: number[] = [];
    reloj.programar(10, () => vistos.push(reloj.ahora()));
    reloj.programar(30, () => vistos.push(reloj.ahora()));
    reloj.avanzar(100);
    expect(vistos).toEqual([10, 30]);
    // Al terminar el avance, el reloj queda en el destino.
    expect(reloj.ahora()).toBe(100);
  });

  it("cancelar evita el disparo y se puede llamar dos veces sin error", () => {
    const reloj = crearRelojFalso();
    const llamadas: string[] = [];
    const cancelar = reloj.programar(10, () => llamadas.push("x"));
    expect(reloj.pendientes()).toBe(1);
    cancelar();
    cancelar();
    expect(reloj.pendientes()).toBe(0);
    reloj.avanzar(100);
    expect(llamadas).toEqual([]);
  });

  it("dispara los callbacks que se programan dentro de otro callback si vencen en el avance", () => {
    const reloj = crearRelojFalso();
    const vistos: string[] = [];
    reloj.programar(10, () => {
      vistos.push(`a@${reloj.ahora()}`);
      // Se programa a +20 desde el instante 10: vence en 30.
      reloj.programar(20, () => vistos.push(`b@${reloj.ahora()}`));
    });
    reloj.avanzar(50);
    expect(vistos).toEqual(["a@10", "b@30"]);
  });

  it("no dispara un callback anidado que vence después del avance", () => {
    const reloj = crearRelojFalso();
    const vistos: string[] = [];
    reloj.programar(10, () => {
      vistos.push(`a@${reloj.ahora()}`);
      reloj.programar(20, () => vistos.push(`b@${reloj.ahora()}`));
    });
    reloj.avanzar(15);
    // El anidado vence en 30: queda pendiente.
    expect(vistos).toEqual(["a@10"]);
    expect(reloj.pendientes()).toBe(1);
    reloj.avanzar(15);
    expect(vistos).toEqual(["a@10", "b@30"]);
    expect(reloj.ahora()).toBe(30);
  });

  it("una espera de 0 no corre hasta el siguiente avance", () => {
    const reloj = crearRelojFalso();
    const llamadas: string[] = [];
    reloj.programar(0, () => llamadas.push("x"));
    // Como setTimeout(…, 0): nunca corre de forma síncrona.
    expect(llamadas).toEqual([]);
    reloj.avanzar(0);
    expect(llamadas).toEqual(["x"]);
  });

  it("avanzar rechaza valores negativos o NaN", () => {
    const reloj = crearRelojFalso();
    expect(() => reloj.avanzar(-1)).toThrow(RangeError);
    expect(() => reloj.avanzar(Number.NaN)).toThrow(RangeError);
  });

  it("un callback puede cancelar otra tarea pendiente", () => {
    const reloj = crearRelojFalso();
    const llamadas: string[] = [];
    let cancelarB: () => void = () => {};
    reloj.programar(10, () => {
      llamadas.push("a");
      cancelarB();
    });
    cancelarB = reloj.programar(20, () => llamadas.push("b"));
    reloj.avanzar(50);
    // "b" estaba pendiente cuando "a" la canceló, así que no corre.
    expect(llamadas).toEqual(["a"]);
  });
});

describe("relojReal", () => {
  it("ahora() devuelve un número que no retrocede", () => {
    const a = relojReal.ahora();
    const b = relojReal.ahora();
    expect(typeof a).toBe("number");
    expect(b).toBeGreaterThanOrEqual(a);
  });

  it("programa con setTimeout y permite cancelar", () => {
    // Temporizadores falsos de Vitest: no se espera tiempo real.
    vi.useFakeTimers();
    try {
      const llamadas: string[] = [];
      relojReal.programar(100, () => llamadas.push("a"));
      const cancelar = relojReal.programar(100, () => llamadas.push("b"));
      cancelar();
      vi.advanceTimersByTime(99);
      expect(llamadas).toEqual([]);
      vi.advanceTimersByTime(1);
      // Solo corre la que no se canceló.
      expect(llamadas).toEqual(["a"]);
    } finally {
      // Siempre se restauran los temporizadores reales, aunque falle una aserción.
      vi.useRealTimers();
    }
  });
});