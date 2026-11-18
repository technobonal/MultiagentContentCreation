// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import {
  aplicarSlideManual,
  camposPorSlide,
  slideManualVigente,
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

describe("slideManualVigente", () => {
  it("es null sin elección", () => {
    expect(slideManualVigente(null, 24)).toBeNull();
  });

  it("devuelve el slide mientras el seq no cambie", () => {
    expect(slideManualVigente({ slide: 6, seq: 24 }, 24)).toBe(6);
  });

  it("se suelta cuando llega un evento nuevo o se salta a otro punto", () => {
    expect(slideManualVigente({ slide: 6, seq: 24 }, 25)).toBeNull();
    expect(slideManualVigente({ slide: 6, seq: 24 }, 10)).toBeNull();
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