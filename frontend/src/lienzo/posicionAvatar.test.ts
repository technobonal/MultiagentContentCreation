// ---------------------------------------------------------------------------
// posicionAvatar.test.ts — Pruebas de actividadDeEstado (función pura del avatar activo).
// Se apoyan en la grabación real b5_cifra_inventada y en el reductor: para cada seq
// se reduce la grabación hasta ese evento y se mira qué hace el avatar. La tabla fija
// la posición de cada tipo y comprueba que el tipo coincida, así un cambio del fixture
// se nota con un mensaje claro.
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { cargarGrabacion, listarGrabaciones } from "../lib/grabacion.ts";
import { crearEstadoInicial, reducirTodos } from "../timeline/reducer.ts";
import { actividadDeEstado } from "./posicionAvatar.ts";
import type { AccionAvatar, DestinoAvatar } from "./posicionAvatar.ts";

// Solo se corre si la grabación real existe en contracts/recordings.
const hayGrabacion = listarGrabaciones().includes("b5_cifra_inventada");

// Fila de la tabla: seq de la grabación, tipo esperado y lo que debe hacer el avatar.
type Caso = [number, string, AccionAvatar, DestinoAvatar];

// Un caso por cada tipo de evento que aparece en la grabación de 24 eventos.
const CASOS: Caso[] = [
  [1, "run_iniciada", "procesar", "centro"],
  [2, "fuente_indexada", "procesar", "centro"],
  [3, "brief_emitido", "pensar", "centro"],
  [4, "plantilla_elegida", "pensar", "centro"],
  [5, "texto_propuesto", "escribir", "campo"],
  [8, "colocar_fondo", "pintar", "esquina"],
  [11, "escribir_texto", "escribir", "campo"],
  [14, "verificacion_fidelidad", "revisar", "afirmacion"],
  [16, "hallazgo_abierto", "revisar", "afirmacion"],
  [18, "corregir", "escribir", "campo"],
  [20, "hallazgo_corregido", "revisar", "afirmacion"],
  [21, "aprobacion_solicitada", "procesar", "centro"],
  [22, "editada", "escribir", "campo"],
  [23, "aprobada", "aprobar", "centro"],
  [24, "run_finalizada", "procesar", "centro"],
];

describe.skipIf(!hayGrabacion)("actividadDeEstado con la grabación real b5_cifra_inventada", () => {
  const grabacion = cargarGrabacion("b5_cifra_inventada");

  // Reduce la grabación hasta el seq indicado (inclusive) y devuelve el estado.
  const hasta = (seq: number) => reducirTodos(crearEstadoInicial(), grabacion.eventos.slice(0, seq));

  it("sin eventos aplicados no hay actividad", () => {
    expect(actividadDeEstado(crearEstadoInicial(), "es")).toBeNull();
  });

  it.each(CASOS)("seq %i (%s): acción %s, destino %s", (seq, tipo, accion, destino) => {
    // Guarda: el evento de esa posición debe ser del tipo que dice la tabla.
    expect(grabacion.eventos[seq - 1]?.tipo).toBe(tipo);

    const actividad = actividadDeEstado(hasta(seq), "es");
    expect(actividad).not.toBeNull();
    expect(actividad?.accion).toBe(accion);
    expect(actividad?.destino).toBe(destino);
    // La clave cambia con cada evento y reinicia la animación de la burbuja.
    expect(actividad?.clave).toBe(String(seq));
    // El agente es el que emitió el último evento.
    expect(actividad?.agente).toBe(grabacion.eventos[seq - 1]?.agente);
    // Toda burbuja trae texto.
    expect(actividad?.burbuja.length).toBeGreaterThan(0);
  });

  // Cada colocar_fondo (seq 8, 9 y 10) nombra el slide que pinta (1, 3 y 4).
  it.each([
    [8, 1],
    [9, 3],
    [10, 4],
  ])("seq %i: la burbuja del fondo nombra el slide %i", (seq, slide) => {
    expect(grabacion.eventos[seq - 1]?.tipo).toBe("colocar_fondo");
    expect(actividadDeEstado(hasta(seq), "es")?.burbuja).toBe(`Pintando el fondo del slide ${slide}…`);
  });

  // Las burbujas de revisión llevan el id de la afirmación o del hallazgo, nunca vacío.
  it("verificación, hallazgo abierto y reevaluación incluyen un id en la burbuja", () => {
    // \S+ exige al menos un carácter de id antes de los puntos suspensivos.
    expect(actividadDeEstado(hasta(14), "es")?.burbuja).toMatch(/^Verificando \S+…$/);
    expect(actividadDeEstado(hasta(16), "es")?.burbuja).toMatch(/^Abriendo hallazgo \S+…$/);
    expect(actividadDeEstado(hasta(20), "es")?.burbuja).toMatch(/^Reevaluando \S+…$/);
  });

  it("en portugués la burbuja cambia de idioma, pero no la acción ni el destino", () => {
    const es = actividadDeEstado(hasta(1), "es");
    // IdiomaFase = "es" | "pt-BR": el portugués se pide con "pt-BR".
    const pt = actividadDeEstado(hasta(1), "pt-BR");
    expect(es?.burbuja).toBe("Iniciando la ejecución…");
    expect(pt?.burbuja).toBe("Iniciando a execução…");
    expect(pt?.accion).toBe(es?.accion);
    expect(pt?.destino).toBe(es?.destino);
  });

  it("es pura: el mismo estado da la misma actividad", () => {
    const estado = hasta(12);
    expect(actividadDeEstado(estado, "es")).toEqual(actividadDeEstado(estado, "es"));
  });
});