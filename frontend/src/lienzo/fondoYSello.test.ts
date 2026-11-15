// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import type { Medidor } from "./ajusteTexto.ts";
import { pintarLienzo } from "./pintarLienzo.ts";
import { textoDelSello } from "./sello.ts";
import { calcularSello, crearEstadoInicial } from "../timeline/reducer.ts";
import type { Estado } from "../timeline/types.ts";

// Medidor falso: todo cabe en una línea.
const unaLinea: Medidor = () => 1;

// Ledger con una afirmación factual respaldada (el recuento exacto lo define calcularSello).
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

// Raíz mínima: fondo, slide 1 y slide 6 con el campo del sello.
function crearRaiz(): HTMLElement {
  const raiz = document.createElement("div");
  raiz.innerHTML = `<svg>
    <rect id="fondo" fill="#0F172A"/>
    <g id="slide-1" class="slide"></g>
    <g id="slide-6" class="slide">
      <foreignObject data-campo="{{sello_revision}}" data-lineas-max="1" data-fuente-min="24"><div style="font-size:24px;line-height:40px;"></div></foreignObject>
    </g>
  </svg>`;
  return raiz;
}

// Estado de prueba con el slide activo, fondos y ledger indicados.
function estadoCon(parcial: {
  slideActivo?: number;
  fondos?: Estado["lienzo"]["fondos"];
  ledger?: Estado["ledger"];
}): Estado {
  const base = crearEstadoInicial();
  return {
    ...base,
    slideActivo: parcial.slideActivo ?? 1,
    ledger: parcial.ledger ?? base.ledger,
    lienzo: { ...base.lienzo, fondos: parcial.fondos ?? base.lienzo.fondos },
  };
}

describe("fondo del lienzo", () => {
  it("aplica el color del slide activo y restaura el de la plantilla al salir", () => {
    const raiz = crearRaiz();
    const rect = raiz.querySelector("#fondo")!;
    const fondos = { 1: { tipo: "color", valor: "#112233" } } as const;

    pintarLienzo(raiz, estadoCon({ fondos, slideActivo: 1 }), () => unaLinea);
    expect(rect.getAttribute("fill")).toBe("#112233");

    // En el slide 6 no hay fondo propio: vuelve al color de la plantilla.
    pintarLienzo(raiz, estadoCon({ fondos, slideActivo: 6 }), () => unaLinea);
    expect(rect.getAttribute("fill")).toBe("#0F172A");
  });

  it("ignora un fondo de tipo imagen en el MVP", () => {
    const raiz = crearRaiz();
    const fondos = { 1: { tipo: "imagen", referencia: "x.png", licencia: "CC0" } } as const;
    pintarLienzo(raiz, estadoCon({ fondos }), () => unaLinea);
    expect(raiz.querySelector("#fondo")!.getAttribute("fill")).toBe("#0F172A");
  });
});

describe("sello de revisión", () => {
  it("es null mientras el ledger está vacío", () => {
    expect(textoDelSello(estadoCon({}))).toBeNull();
  });

  it("formatea N de M con lo que calcula el reductor", () => {
    const estado = estadoCon({ ledger: ledgerUno });
    const sello = calcularSello(ledgerUno);
    expect(sello.afirmaciones_totales).toBeGreaterThan(0);
    expect(textoDelSello(estado)).toBe(
      `${sello.afirmaciones_respaldadas} de ${sello.afirmaciones_totales} afirmaciones respaldadas`,
    );
  });

  it("se pinta en el campo del slide de fuentes sin que llegue ningún evento de texto", () => {
    const raiz = crearRaiz();
    pintarLienzo(raiz, estadoCon({ slideActivo: 6, ledger: ledgerUno }), () => unaLinea);
    const div = raiz.querySelector<HTMLElement>("#slide-6 div")!;
    expect(div.textContent).toContain("afirmaciones respaldadas");
  });

  it("deja el campo vacío si todavía no hay afirmaciones", () => {
    const raiz = crearRaiz();
    pintarLienzo(raiz, estadoCon({ slideActivo: 6 }), () => unaLinea);
    expect(raiz.querySelector<HTMLElement>("#slide-6 div")!.textContent).toBe("");
  });
});