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
// --- Imágenes (evento colocar_imagen) -------------------------------------------------------------

function raizConHueco(): HTMLElement {
  const raiz = document.createElement("div");
  raiz.innerHTML = `<svg>
    <g id="slide-2" class="slide">
      <g id="imagen-producto" data-campo="{{imagen_producto}}" data-opcional="true">
        <title>Foto del producto</title>
        <rect x="80" y="698" width="920" height="422"/>
        <image x="80" y="698" width="920" height="422" href="{{imagen_producto}}"/>
      </g>
    </g>
  </svg>`;
  return raiz;
}

const IMAGEN_COLOCADA = { referencia: "foto-2", licencia: "Uso autorizado", texto_alternativo: "Un edificio al atardecer" };

function estadoConImagen(runId: string | null, imagen: typeof IMAGEN_COLOCADA | null = IMAGEN_COLOCADA): Estado {
  const base = crearEstadoInicial();
  const imagenes: Estado["lienzo"]["imagenes"] = imagen ? { 2: { imagen_producto: imagen } } : {};
  return { ...base, slideActivo: 2, runId, lienzo: { ...base.lienzo, imagenes } };
}

function partes(raiz: HTMLElement) {
  const grupo = raiz.querySelector<SVGElement>("#imagen-producto") as SVGElement;
  const img = grupo.querySelector("image") as SVGImageElement;
  const hueco = grupo.querySelector("rect") as SVGElement;
  return { grupo, img, hueco };
}

describe("pintarLienzo: imagen de la fuente", () => {
  it("sin imagen el hueco opcional sigue oculto", () => {
    const raiz = raizConHueco();
    pintarLienzo(raiz, estadoConImagen("run_1", null), fabricaFalsa);
    expect(partes(raiz).grupo.style.display).toBe("none");
  });

  it("con imagen pide la URL del run, muestra el hueco y pone el texto alternativo y la licencia", () => {
    const raiz = raizConHueco();
    pintarLienzo(raiz, estadoConImagen("run_abc"), fabricaFalsa);
    const { grupo, img } = partes(raiz);
    expect(grupo.style.display).toBe("");
    expect(img.getAttribute("href")).toBe("/api/runs/run_abc/imagenes/foto-2");
    expect(img.getAttribute("aria-label")).toBe("Un edificio al atardecer");
    expect(grupo.querySelector("title")?.textContent).toBe("Un edificio al atardecer");
    expect(grupo.getAttribute("data-licencia")).toBe("Uso autorizado");
  });

  it("al cargar marca la imagen y oculta el borde punteado; si falla, deja el hueco a la vista", () => {
    const raiz = raizConHueco();
    pintarLienzo(raiz, estadoConImagen("run_abc"), fabricaFalsa);
    const { img, hueco } = partes(raiz);
    expect(img.hasAttribute("data-cargada")).toBe(false);
    img.dispatchEvent(new Event("load"));
    expect(img.getAttribute("data-cargada")).toBe("true");
    expect(hueco.style.display).toBe("none");

    const otra = raizConHueco();
    pintarLienzo(otra, estadoConImagen("run_abc"), fabricaFalsa);
    const p = partes(otra);
    p.img.dispatchEvent(new Event("error"));
    expect(p.img.getAttribute("data-error")).toBe("true");
    expect(p.hueco.style.display).toBe("");
  });

  it("es idempotente: repintar la misma imagen no reinicia la carga", () => {
    const raiz = raizConHueco();
    pintarLienzo(raiz, estadoConImagen("run_abc"), fabricaFalsa);
    partes(raiz).img.dispatchEvent(new Event("load"));
    pintarLienzo(raiz, estadoConImagen("run_abc"), fabricaFalsa);
    expect(partes(raiz).img.getAttribute("data-cargada")).toBe("true");
  });

  it("una referencia nueva reinicia la carga", () => {
    const raiz = raizConHueco();
    pintarLienzo(raiz, estadoConImagen("run_abc"), fabricaFalsa);
    partes(raiz).img.dispatchEvent(new Event("load"));
    pintarLienzo(raiz, estadoConImagen("run_abc", { ...IMAGEN_COLOCADA, referencia: "foto-3" }), fabricaFalsa);
    const { img } = partes(raiz);
    expect(img.getAttribute("href")).toBe("/api/runs/run_abc/imagenes/foto-3");
    expect(img.hasAttribute("data-cargada")).toBe(false);
  });

  it("sin run (grabación local) no se pide ninguna imagen", () => {
    const raiz = raizConHueco();
    pintarLienzo(raiz, estadoConImagen(null), fabricaFalsa);
    const { grupo, img } = partes(raiz);
    expect(img.hasAttribute("href")).toBe(false);
    expect(grupo.style.display).toBe("none");
  });

  it("si la imagen deja de estar en el estado (salto atrás) el campo vuelve a ocultarse", () => {
    const raiz = raizConHueco();
    pintarLienzo(raiz, estadoConImagen("run_abc"), fabricaFalsa);
    pintarLienzo(raiz, estadoConImagen("run_abc", null), fabricaFalsa);
    const { grupo, img } = partes(raiz);
    expect(grupo.style.display).toBe("none");
    expect(img.hasAttribute("href")).toBe(false);
  });

  it("un id de run con caracteres raros se escapa en la URL", () => {
    const raiz = raizConHueco();
    pintarLienzo(raiz, estadoConImagen("run x/../y"), fabricaFalsa);
    expect(partes(raiz).img.getAttribute("href")).toBe("/api/runs/run%20x%2F..%2Fy/imagenes/foto-2");
  });
});

// --- Tipografía: el cuerpo sube hasta quedar bajo el título ------------------------------------------

function raizConSeguidor(atributos = 'data-sigue="titulo" data-separacion="40"'): HTMLElement {
  const raiz = document.createElement("div");
  raiz.innerHTML = `<svg><g id="slide-1" class="slide">
      <foreignObject x="80" y="200" width="920" height="222" data-campo="{{titulo}}" data-lineas-max="3" data-fuente-min="56"><div style="font-size:64px;line-height:74px;"></div></foreignObject>
      <foreignObject x="80" y="500" width="920" height="150" data-campo="{{cuerpo}}" data-lineas-max="3" data-fuente-min="32" ${atributos}><div style="font-size:36px;line-height:50px;"></div></foreignObject>
    </g></svg>`;
  return raiz;
}

const yDelCuerpo = (raiz: HTMLElement) => raiz.querySelector('[data-campo="{{cuerpo}}"]')?.getAttribute("y");

describe("pintarLienzo: el cuerpo acompaña al título", () => {
  it("con un título de una línea sube hasta quedar debajo, con la separación pedida", () => {
    const raiz = raizConSeguidor();
    pintarLienzo(raiz, estadoCon({ 1: { titulo: "corto", cuerpo: "texto" } }), fabricaFalsa);
    expect(yDelCuerpo(raiz)).toBe(String(200 + 74 + 40));
  });

  it("nunca baja de su sitio en la plantilla, aunque el título ocupe varias líneas", () => {
    const raiz = raizConSeguidor('data-sigue="titulo" data-separacion="200"');
    pintarLienzo(raiz, estadoCon({ 1: { titulo: "a".repeat(80), cuerpo: "texto" } }), fabricaFalsa);
    expect(yDelCuerpo(raiz)).toBe("500");
  });

  it("al repintar con otro título parte de la posición original, no de la anterior", () => {
    const raiz = raizConSeguidor();
    pintarLienzo(raiz, estadoCon({ 1: { titulo: "corto" } }), fabricaFalsa);
    pintarLienzo(raiz, estadoCon({ 1: { titulo: "a".repeat(40) } }), fabricaFalsa); // dos líneas
    expect(yDelCuerpo(raiz)).toBe(String(200 + 2 * 74 + 40));
  });

  it("sin título vuelve a su sitio", () => {
    const raiz = raizConSeguidor();
    pintarLienzo(raiz, estadoCon({ 1: { titulo: "corto" } }), fabricaFalsa);
    pintarLienzo(raiz, estadoCon({}), fabricaFalsa);
    expect(yDelCuerpo(raiz)).toBe("500");
  });

  it("sin data-sigue no se mueve (la plantilla actual queda igual)", () => {
    const raiz = raizConSeguidor("");
    pintarLienzo(raiz, estadoCon({ 1: { titulo: "corto" } }), fabricaFalsa);
    expect(yDelCuerpo(raiz)).toBe("500");
  });
});
