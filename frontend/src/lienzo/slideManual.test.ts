// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import {
  aplicarSlideManual,
  camposPorSlide,
  problemasDelSlide,
  slideTieneCalculado,
} from "./slideManual.ts";
import { crearEstadoInicial } from "../timeline/reducer.ts";
import type { Estado } from "../timeline/types.ts";

// Ledger con una afirmación factual respaldada (misma forma que en fondoYSello.test.ts).
const ledgerUno: Estado["ledger"] = {
  a1: {
    actual: {
      seq: 1,
      slide: 3,
      afirmacion: "El Sprint dura un mes o menos.",
      clasificacion: "factual",
      veredicto: "respaldada",
      cita: null,
      motivo: "Coincide con la fuente.",
    },
    historial: [],
  },
};

// Raíz mínima: slide 1 con título, slide 6 con los tres campos calculados y un id inválido.
function crearRaiz(): HTMLElement {
  const raiz = document.createElement("div");
  raiz.innerHTML = `<svg>
    <g id="slide-1" class="slide">
      <foreignObject data-campo="{{titulo}}"><div></div></foreignObject>
    </g>
    <g id="slide-6" class="slide">
      <foreignObject data-campo="{{fuente_atribucion}}"><div></div></foreignObject>
      <foreignObject data-campo="{{fuente_licencia}}"><div></div></foreignObject>
      <foreignObject data-campo="{{sello_revision}}"><div></div></foreignObject>
    </g>
    <g id="otro" class="slide"></g>
  </svg>`;
  return raiz;
}

describe("camposPorSlide", () => {
  it("devuelve los nombres de campo sin llaves, por número de slide", () => {
    const mapa = camposPorSlide(crearRaiz());
    expect(mapa[1]).toEqual(["titulo"]);
    expect(mapa[6]).toEqual(["fuente_atribucion", "fuente_licencia", "sello_revision"]);
  });

  it("ignora un <g class='slide'> cuyo id no es slide-N", () => {
    const mapa = camposPorSlide(crearRaiz());
    // Solo quedan los slides 1 y 6.
    expect(Object.keys(mapa).sort()).toEqual(["1", "6"]);
  });
});

describe("slideTieneCalculado", () => {
  it("es true si algún campo devuelve texto", () => {
    const calcular = (_e: Estado, campo: string) =>
      campo === "sello_revision" ? "2 de 2 afirmaciones respaldadas" : undefined;
    expect(slideTieneCalculado(crearEstadoInicial(), ["titulo", "sello_revision"], calcular)).toBe(true);
  });

  it("es false si todos devuelven undefined, vacío o solo espacios", () => {
    const valores = [undefined, "", "   "];
    // Un caso por cada forma de "sin texto".
    for (const valor of valores) {
      expect(slideTieneCalculado(crearEstadoInicial(), ["a"], () => valor)).toBe(false);
    }
  });

  it("es false si el slide no tiene campos", () => {
    expect(slideTieneCalculado(crearEstadoInicial(), [], () => "x")).toBe(false);
  });

  it("con el calculador real: el sello aparece cuando el ledger tiene afirmaciones", () => {
    const base = crearEstadoInicial();
    expect(slideTieneCalculado(base, ["sello_revision"])).toBe(false);
    expect(slideTieneCalculado({ ...base, ledger: ledgerUno }, ["sello_revision"])).toBe(true);
  });
});

describe("problemasDelSlide", () => {
  const h = (id: string, slide: number | null, estado: "abierto" | "corregido", seq: number) =>
    ({ hallazgo_id: id, slide, estado, abiertoEnSeq: seq }) as unknown as Estado["hallazgos"][string];
  const estado = {
    ...crearEstadoInicial(),
    hallazgos: { h3: h("h3", 2, "abierto", 30), h1: h("h1", 2, "corregido", 10), h2: h("h2", 2, "abierto", 20), h4: h("h4", 3, "abierto", 40), h5: h("h5", null, "abierto", 50) },
  };

  it("separa abiertos de corregidos, solo del slide pedido y en orden de aparición", () => {
    const { abiertos, corregidos } = problemasDelSlide(estado, 2);
    expect(abiertos.map((x) => x.hallazgo_id)).toEqual(["h2", "h3"]);
    expect(corregidos.map((x) => x.hallazgo_id)).toEqual(["h1"]);
  });

  it("un slide sin hallazgos devuelve las dos listas vacías", () => {
    expect(problemasDelSlide(estado, 6)).toEqual({ abiertos: [], corregidos: [] });
  });
});

describe("aplicarSlideManual", () => {
  it("sin slide manual devuelve el mismo objeto", () => {
    const estado = crearEstadoInicial();
    expect(aplicarSlideManual(estado, null)).toBe(estado);
  });

  it("con slide manual fuerza slideActivo sin mutar el original ni copiar el resto", () => {
    const estado = { ...crearEstadoInicial(), ledger: ledgerUno };
    const vista = aplicarSlideManual(estado, 6);
    expect(vista.slideActivo).toBe(6);
    // El original queda intacto.
    expect(estado.slideActivo).toBe(1);
    // El resto comparte referencia (no fuerza repintados de las miniaturas).
    expect(vista.ledger).toBe(estado.ledger);
  });
});