import { describe, expect, it } from "vitest";
import { crearEstadoInicial } from "../timeline/reducer.ts";
import type { Estado } from "../timeline/types.ts";
import { especialidadDe, especialidadDeAgente, nombreEspecialidad } from "./fase.ts";

function estadoCon(tipo: string | null, final: Estado["final"] = null): Estado {
  const base = crearEstadoInicial();
  const agentes = tipo === null ? {} : { director_arte: { seq: 3, tipo } };
  return { ...base, agentes: agentes as unknown as Estado["agentes"], final };
}

describe("especialidades del director de arte", () => {
  it("cada paso tiene su oficio", () => {
    expect(especialidadDe("escribir_texto")).toBe("tipografia");
    expect(especialidadDe("colocar_imagen")).toBe("fotografia");
    expect(especialidadDe("colocar_fondo")).toBeNull();
    expect(especialidadDe("verificacion_fidelidad")).toBeNull();
  });

  it("los nombres salen en los dos idiomas", () => {
    expect(nombreEspecialidad("fotografia", "es")).toBe("Fotografía");
    expect(nombreEspecialidad("tipografia", "pt-BR")).toBe("Tipografia");
  });

  it("la ficha del director de arte muestra el oficio de su último paso", () => {
    expect(especialidadDeAgente(estadoCon("colocar_imagen"), "director_arte")).toBe("fotografia");
    expect(especialidadDeAgente(estadoCon("escribir_texto"), "director_arte")).toBe("tipografia");
  });

  it("pintar el fondo del último slide no borra la tipografía en curso", () => {
    const base = estadoCon("colocar_fondo");
    expect(especialidadDeAgente(base, "director_arte")).toBeNull(); // todavía no escribió nada
    const conTextos = { ...base, lienzo: { ...base.lienzo, textos: { 1: { titulo: "Hola" } } } };
    expect(especialidadDeAgente(conTextos, "director_arte")).toBe("tipografia");
    const conFotos = { ...conTextos, lienzo: { ...conTextos.lienzo, imagenes: { 1: { x: { referencia: "foto-1", licencia: "L", texto_alternativo: "t" } } } } };
    expect(especialidadDeAgente(conFotos, "director_arte")).toBeNull();
  });

  it("no se muestra en otros agentes, antes de actuar ni cuando la ejecución ya terminó", () => {
    expect(especialidadDeAgente(estadoCon("escribir_texto"), "redactor")).toBeNull();
    expect(especialidadDeAgente(estadoCon(null), "director_arte")).toBeNull();
    expect(especialidadDeAgente(estadoCon("colocar_imagen", {} as Estado["final"]), "director_arte")).toBeNull();
  });
});
