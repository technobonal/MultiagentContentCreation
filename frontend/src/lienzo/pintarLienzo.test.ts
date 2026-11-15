// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import type { Medidor } from "./ajusteTexto.ts";
import { pintarLienzo } from "./pintarLienzo.ts";
import type { FabricaMedidor } from "./pintarLienzo.ts";
import { crearEstadoInicial } from "../timeline/reducer.ts";
import type { Estado, TextosPorSlide } from "../timeline/types.ts";

// Medidor falso: cada carácter ocupa 0,55 × la fuente y la caja mide 920 px de ancho.
const medidorFalso: Medidor = (texto, fuentePx) => {
  const porLinea = Math.floor(920 / (fuentePx * 0.55));
  return Math.max(1, Math.ceil(texto.length / porLinea));
};
const fabricaFalsa: FabricaMedidor = () => medidorFalso;

// Mini SVG con dos slides: título (64 px, mín. 56, máx. 3 líneas) y subtítulo opcional.
function crearRaiz(): HTMLElement {
  const raiz = document.createElement("div");
  raiz.innerHTML = `<svg>
    <g id="slide-1" class="slide">
      <foreignObject data-campo="{{titulo}}" data-lineas-max="3" data-fuente-min="56"><div style="font-size:64px;line-height:74px;"></div></foreignObject>
      <foreignObject data-campo="{{subtitulo}}" data-lineas-max="3" data-fuente-min="32" data-opcional="true"><div style="font-size:36px;line-height:50px;"></div></foreignObject>
    </g>
    <g id="slide-2" class="slide">
      <foreignObject data-campo="{{titulo}}" data-lineas-max="3" data-fuente-min="56"><div style="font-size:64px;line-height:74px;"></div></foreignObject>
    </g>
  </svg>`;
  return raiz;
}

// Estado de prueba con los textos dados y el slide activo indicado.
function estadoCon(textos: TextosPorSlide, slideActivo = 1): Estado {
  const base = crearEstadoInicial();
  return { ...base, slideActivo, lienzo: { ...base.lienzo, textos } };
}

// Devuelve el div de un campo dentro de un slide.
function div(raiz: HTMLElement, slide: number, campo: string): HTMLElement {
  const el = raiz.querySelector<HTMLElement>(`#slide-${slide} [data-campo="{{${campo}}}"] div`);
  // Si el fixture cambia y no se encuentra, la prueba debe fallar con un mensaje claro.
  if (!el) throw new Error(`No se encontró ${campo} en el slide ${slide}`);
  return el;
}

describe("pintarLienzo", () => {
  it("escribe el texto y ajusta el tamaño en el slide activo", () => {
    const raiz = crearRaiz();
    const r = pintarLienzo(raiz, estadoCon({ 1: { titulo: "a".repeat(80) } }), fabricaFalsa);
    const titulo = div(raiz, 1, "titulo");
    expect(titulo.textContent).toBe("a".repeat(80));
    expect(titulo.style.fontSize).toBe("60px");
    expect(titulo.style.lineHeight).toBe("69px");
    expect(titulo.dataset.estado).toBe("encogido");
    expect(r.find((c) => c.campo === "titulo" && c.slide === 1)?.resultado?.estado).toBe("encogido");
  });

  it("marca el desborde de forma visible y no recorta el texto", () => {
    const raiz = crearRaiz();
    pintarLienzo(raiz, estadoCon({ 1: { titulo: "a".repeat(400) } }), fabricaFalsa);
    const titulo = div(raiz, 1, "titulo");
    expect(titulo.dataset.estado).toBe("desborda");
    expect(titulo.style.outline).toContain("dashed");
    expect(titulo.style.fontSize).toBe("56px");
    expect(titulo.textContent).toHaveLength(400);
  });

  it("reajusta desde el tamaño base cuando el texto se corrige", () => {
    const raiz = crearRaiz();
    pintarLienzo(raiz, estadoCon({ 1: { titulo: "a".repeat(80) } }), fabricaFalsa);
    expect(div(raiz, 1, "titulo").style.fontSize).toBe("60px");
    // Texto corto: debe volver a 64 px y quitar cualquier marcador.
    pintarLienzo(raiz, estadoCon({ 1: { titulo: "a".repeat(20) } }), fabricaFalsa);
    const titulo = div(raiz, 1, "titulo");
    expect(titulo.style.fontSize).toBe("64px");
    expect(titulo.style.lineHeight).toBe("74px");
    expect(titulo.dataset.estado).toBe("ok");
  });

  it("oculta el campo opcional sin texto y lo muestra cuando llega", () => {
    const raiz = crearRaiz();
    const sub = raiz.querySelector<HTMLElement>('#slide-1 [data-campo="{{subtitulo}}"]')!;
    pintarLienzo(raiz, estadoCon({ 1: { titulo: "hola" } }), fabricaFalsa);
    expect(sub.style.display).toBe("none");
    pintarLienzo(raiz, estadoCon({ 1: { titulo: "hola", subtitulo: "detalle" } }), fabricaFalsa);
    expect(sub.style.display).toBe("");
  });

  it("deja vacío un campo obligatorio que todavía no se escribió", () => {
    const raiz = crearRaiz();
    pintarLienzo(raiz, estadoCon({}), fabricaFalsa);
    expect(div(raiz, 1, "titulo").textContent).toBe("");
  });

  it("solo ajusta el slide activo y reajusta al activarse otro", () => {
    const raiz = crearRaiz();
    const textos = { 2: { titulo: "a".repeat(80) } };
    // Slide 2 inactivo: texto escrito, pero sin ajuste.
    const r1 = pintarLienzo(raiz, estadoCon(textos, 1), fabricaFalsa);
    expect(div(raiz, 2, "titulo").textContent).toBe("a".repeat(80));
    expect(div(raiz, 2, "titulo").style.fontSize).toBe("64px");
    expect(r1.find((c) => c.slide === 2)?.resultado).toBeNull();
    expect(raiz.querySelector("#slide-1")!.classList.contains("activo")).toBe(true);
    // Se activa el slide 2: ahora sí se ajusta.
    pintarLienzo(raiz, estadoCon(textos, 2), fabricaFalsa);
    expect(div(raiz, 2, "titulo").style.fontSize).toBe("60px");
    expect(raiz.querySelector("#slide-1")!.classList.contains("activo")).toBe(false);
    expect(raiz.querySelector("#slide-2")!.classList.contains("activo")).toBe(true);
  });
});