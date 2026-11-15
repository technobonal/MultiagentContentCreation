// ---------------------------------------------------------------------------
// ordenador.test.ts — Pruebas del ordenador (Paso 3, escritas antes que el código).
// Cubre: orden, idempotencia, duplicados con contenido distinto, huecos, inicio
// distinto de 1, run mezclado, seq inválido y no mutación de la entrada.
// Si existe la grabación real b5_cifra_inventada, se corre además un bloque con ella.
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { cargarGrabacion, listarGrabaciones } from "../lib/grabacion.ts";
import { conRun, conSeq, conTexto, crearSecuencia, porSeq } from "./eventosPrueba.ts";
import { ordenar } from "./ordenador.ts";

describe("ordenar", () => {
  it("con entrada vacía devuelve ok, sin eventos y sin problemas", () => {
    const r = ordenar([]);
    expect(r.ok).toBe(true);
    expect(r.eventos).toEqual([]);
    expect(r.problemas).toEqual([]);
  });

  it("deja igual una secuencia que ya viene ordenada", () => {
    const base = crearSecuencia(5);
    const r = ordenar(base);
    expect(r.ok).toBe(true);
    expect(r.eventos.map((e) => e.seq)).toEqual([1, 2, 3, 4, 5]);
  });

  it("ordena por seq una secuencia desordenada", () => {
    const base = crearSecuencia(5);
    // Mismo contenido, pero en el orden 4, 1, 3, 2, 5.
    const desordenada = [4, 1, 3, 2, 5].map((s) => porSeq(base, s));
    const r = ordenar(desordenada);
    expect(r.ok).toBe(true);
    expect(r.eventos.map((e) => e.seq)).toEqual([1, 2, 3, 4, 5]);
  });

  it("no muta la entrada ni crea eventos nuevos", () => {
    // Arreglo congelado: si el ordenador intentara ordenarlo en el lugar, lanzaría.
    const entrada = Object.freeze(crearSecuencia(5).reverse());
    const antes = entrada.map((e) => e.seq);
    let r: ReturnType<typeof ordenar> | undefined;
    expect(() => {
      r = ordenar(entrada);
    }).not.toThrow();
    // La entrada conserva su orden original (5, 4, 3, 2, 1).
    expect(entrada.map((e) => e.seq)).toEqual(antes);
    // Los eventos devueltos son los mismos objetos, no copias.
    expect(r?.eventos.every((e) => entrada.includes(e))).toBe(true);
  });

  it("descarta en silencio un seq repetido con contenido idéntico", () => {
    const base = crearSecuencia(4);
    // Una copia profunda del evento 2: mismo contenido, otro objeto.
    const copia = structuredClone(porSeq(base, 2));
    const r = ordenar([...base, copia]);
    expect(r.ok).toBe(true);
    expect(r.problemas).toEqual([]);
    expect(r.eventos.map((e) => e.seq)).toEqual([1, 2, 3, 4]);
  });

  it("reporta un seq repetido con contenido distinto y no aplica ninguno de los dos", () => {
    const base = crearSecuencia(8);
    const distinto = conTexto(porSeq(base, 7), "Otro texto");
    const r = ordenar([...base, distinto]);
    expect(r.ok).toBe(false);
    // Un solo problema: el hueco que deja el seq 7 excluido no se reporta aparte.
    expect(r.problemas).toHaveLength(1);
    expect(r.problemas.map((p) => p.codigo)).toEqual(["seq_repetido_distinto"]);
    expect(r.problemas.map((p) => p.seq)).toEqual([7]);
    expect(r.eventos.map((e) => e.seq)).toEqual([1, 2, 3, 4, 5, 6, 8]);
  });

  it("reporta un hueco simple", () => {
    // Falta el seq 4.
    const r = ordenar(crearSecuencia(6).filter((e) => e.seq !== 4));
    expect(r.ok).toBe(false);
    expect(r.problemas.map((p) => p.codigo)).toEqual(["hueco"]);
    // El problema apunta al primer seq que llegó después del hueco.
    expect(r.problemas.map((p) => p.seq)).toEqual([5]);
    expect(r.problemas.map((p) => p.detalle).join()).toContain("4");
  });

  it("reporta un hueco de varios seq seguidos como un solo problema", () => {
    // Faltan el 3 y el 4.
    const r = ordenar(crearSecuencia(6).filter((e) => e.seq !== 3 && e.seq !== 4));
    expect(r.problemas).toHaveLength(1);
    expect(r.problemas.map((p) => p.detalle).join()).toContain("3 a 4");
  });

  it("reporta cada hueco por separado cuando hay varios", () => {
    // Faltan el 3 y el 6, que no son contiguos.
    const r = ordenar(crearSecuencia(8).filter((e) => e.seq !== 3 && e.seq !== 6));
    expect(r.problemas.map((p) => p.codigo)).toEqual(["hueco", "hueco"]);
    expect(r.problemas.map((p) => p.seq)).toEqual([4, 7]);
  });

  it("reporta una secuencia que no empieza en 1", () => {
    const r = ordenar(crearSecuencia(5).filter((e) => e.seq >= 2));
    expect(r.ok).toBe(false);
    expect(r.problemas.map((p) => p.codigo)).toEqual(["inicio_distinto_de_1"]);
    expect(r.problemas.map((p) => p.seq)).toEqual([2]);
  });

  it("reporta y excluye un evento de otro run_id", () => {
    const base = crearSecuencia(4);
    const ajeno = conRun(porSeq(crearSecuencia(5), 5), "run_otro");
    const r = ordenar([...base, ajeno]);
    expect(r.ok).toBe(false);
    expect(r.problemas.map((p) => p.codigo)).toEqual(["run_mezclado"]);
    expect(r.eventos.map((e) => e.seq)).toEqual([1, 2, 3, 4]);
  });

  it("reporta y excluye los seq que no son enteros mayores o iguales a 1", () => {
    const base = crearSecuencia(3);
    const modelo = porSeq(base, 1);
    // Cuatro eventos con seq inválido: 0, negativo, decimal y NaN.
    const invalidos = [0, -1, 1.5, Number.NaN].map((s) => conSeq(modelo, s));
    const r = ordenar([...invalidos, ...base]);
    expect(r.problemas.map((p) => p.codigo)).toEqual([
      "seq_invalido",
      "seq_invalido",
      "seq_invalido",
      "seq_invalido",
    ]);
    // El NaN se reporta con seq nulo porque no es un número finito.
    expect(r.problemas.map((p) => p.seq)).toEqual([0, -1, 1.5, null]);
    expect(r.eventos.map((e) => e.seq)).toEqual([1, 2, 3]);
  });

  it("acumula problemas de distinto tipo en una sola pasada", () => {
    const base = crearSecuencia(8).filter((e) => e.seq !== 3); // falta el 3
    const invalido = conSeq(porSeq(base, 1), 0); // seq inválido
    const distinto = conTexto(porSeq(base, 7), "Otro texto"); // repetido con otro contenido
    const r = ordenar([invalido, ...base, distinto]);
    expect(r.ok).toBe(false);
    expect(r.problemas.map((p) => p.codigo)).toEqual([
      "seq_invalido",
      "seq_repetido_distinto",
      "hueco",
    ]);
    // Los eventos limpios quedan ordenados y sin el seq 3 ni el 7.
    expect(r.eventos.map((e) => e.seq)).toEqual([1, 2, 4, 5, 6, 8]);
  });
});

// Solo se corre si la grabación real existe en contracts/recordings.
const hayGrabacion = listarGrabaciones().includes("b5_cifra_inventada");

describe.skipIf(!hayGrabacion)("ordenar con la grabación real b5_cifra_inventada", () => {
  it("la acepta tal cual: 22 eventos, sin problemas y en el mismo orden", () => {
    const grabacion = cargarGrabacion("b5_cifra_inventada");
    const r = ordenar(grabacion.eventos);
    expect(r.ok).toBe(true);
    expect(r.eventos).toHaveLength(22);
    expect(r.eventos.map((e) => e.seq)).toEqual(grabacion.eventos.map((e) => e.seq));
  });

  it("devuelve el mismo orden aunque la entrada llegue invertida", () => {
    const grabacion = cargarGrabacion("b5_cifra_inventada");
    const r = ordenar([...grabacion.eventos].reverse());
    expect(r.ok).toBe(true);
    expect(r.eventos.map((e) => e.seq)).toEqual(grabacion.eventos.map((e) => e.seq));
  });
});