// ---------------------------------------------------------------------------
// colocarImagenEnVivo.ts — Animación del director de arte al colocar una foto en el hueco de la plantilla:
//  1. la etiqueta con su nombre aparece sobre el hueco y el borde punteado late,
//  2. espera a que la imagen cargue (para no revelar un hueco vacío),
//  3. la foto se revela: de ampliada, desenfocada y brillante a nítida, mientras una barra de luz cruza el hueco.
// Las partes puras (qué foto es nueva) están aparte para probarlas sin DOM.
// ---------------------------------------------------------------------------
import gsap from "gsap";
import { colocarEtiqueta } from "./escrituraEnVivo.ts";
import type { Estado } from "../timeline/types.ts";

// Duraciones base (s, a 1x; se dividen por la velocidad). La suma (~3,15 s) tiene que caber en la pausa que el backend
// deja entre foto y foto (`FOTOS_PAUSA_SEG`, 3,5 s): un evento nuevo corta la animación en curso.
const LATIDO_S = 0.25;
const LATIDOS = 2; // idas y vueltas del borde punteado (cada una dura 2 × LATIDO_S)
const REVELADO_S = 1.6;
const BARRIDO_S = 0.9;
const SEGUNDO_BARRIDO_DESDE_S = 0.7; // el segundo barrido arranca así de tarde dentro del revelado
const PAUSA_FINAL_S = 0.3;
const DESVANECER_S = 0.25;
const ANCHO_BARRA = 160;
const ZOOM_INICIAL = 1.3;
const DESENFOQUE_INICIAL_PX = 18;
const BRILLO_INICIAL = 2.2;
// Si la imagen tarda más que esto en cargar, se revela igual (se verá el hueco o el error).
const ESPERA_CARGA_MAX_MS = 4000;

export interface ImagenEnLienzo {
  readonly slide: number;
  readonly campo: string;
}

/** Mapa «slide:campo» -> referencia de las imágenes dibujadas. */
export function imagenesColocadas(estado: Estado): Map<string, string> {
  const mapa = new Map<string, string>();
  for (const [slide, campos] of Object.entries(estado.lienzo.imagenes)) {
    for (const [campo, imagen] of Object.entries(campos)) mapa.set(`${slide}:${campo}`, imagen.referencia);
  }
  return mapa;
}

/** La imagen del slide activo que acaba de aparecer o cambiar de referencia (la última, si hay varias); null si no hay. */
export function imagenNueva(previas: ReadonlyMap<string, string>, actuales: ReadonlyMap<string, string>, slideActivo: number): ImagenEnLienzo | null {
  let nueva: ImagenEnLienzo | null = null;
  for (const [clave, referencia] of actuales) {
    if (previas.get(clave) === referencia) continue;
    const [slide, campo] = clave.split(":") as [string, string];
    if (Number(slide) === slideActivo) nueva = { slide: Number(slide), campo };
  }
  return nueva;
}

export interface OpcionesColocacion {
  /** Grupo `[data-campo]` del hueco de imagen (trae el rect punteado y el <image>). */
  readonly grupo: SVGElement;
  readonly etiqueta: HTMLElement;
  readonly marco: HTMLElement;
  readonly nombreAgente: string;
  readonly velocidad?: number;
}

export interface ColocacionEnVivo {
  readonly timeline: gsap.core.Timeline;
  /** Deja el hueco como si no hubiera animación (al cortarla por un evento nuevo o al terminar). Es idempotente. */
  readonly restaurar: () => void;
}

/** Resuelve cuando la imagen ya cargó (o falló), o pasado un tope. */
function esperarCarga(img: Element): Promise<void> {
  if (img.getAttribute("data-cargada") === "true" || img.getAttribute("data-error") === "true") return Promise.resolve();
  return new Promise((resolver) => {
    const fin = () => {
      img.removeEventListener("load", fin);
      img.removeEventListener("error", fin);
      resolver();
    };
    img.addEventListener("load", fin);
    img.addEventListener("error", fin);
    setTimeout(fin, ESPERA_CARGA_MAX_MS);
  });
}

export function colocarImagenEnVivo(o: OpcionesColocacion): ColocacionEnVivo {
  const { grupo, etiqueta, marco, nombreAgente } = o;
  const factor = Math.max(0.1, o.velocidad ?? 1);
  const img = grupo.querySelector<SVGImageElement>("image");
  const hueco = grupo.querySelector<SVGElement>("rect");
  const ns = "http://www.w3.org/2000/svg";
  let barra: SVGRectElement | null = null;

  function restaurar(): void {
    if (img) {
      gsap.killTweensOf(img);
      // Se devuelve el control al CSS (visible cuando cargó) y se quita todo lo que puso la animación.
      img.style.removeProperty("transition");
      gsap.set(img, { clearProps: "opacity,transform,filter,transformOrigin" });
    }
    if (hueco) gsap.set(hueco, { clearProps: "strokeOpacity" });
    barra?.remove();
    barra = null;
    gsap.killTweensOf(etiqueta);
    gsap.set(etiqueta, { opacity: 0 });
  }

  const tl = gsap.timeline({ onComplete: restaurar });
  if (!img || !hueco) {
    tl.to({}, { duration: 0.01 });
    return { timeline: tl, restaurar };
  }

  const x = Number(hueco.getAttribute("x"));
  const y = Number(hueco.getAttribute("y"));
  const ancho = Number(hueco.getAttribute("width"));
  const alto = Number(hueco.getAttribute("height"));

  // El CSS tiene un fundido propio: se apaga mientras GSAP mueve la opacidad cuadro a cuadro.
  img.style.transition = "none";
  gsap.set(img, { opacity: 0, scale: ZOOM_INICIAL, transformOrigin: "50% 50%", filter: `blur(${DESENFOQUE_INICIAL_PX}px) brightness(${BRILLO_INICIAL})` });

  // 1. Etiqueta del agente sobre la esquina del hueco y borde que late.
  etiqueta.textContent = nombreAgente;
  const r = hueco.getBoundingClientRect();
  const m = marco.getBoundingClientRect();
  colocarEtiqueta(etiqueta, marco, r.left - m.left, r.top - m.top);
  tl.set(etiqueta, { opacity: 1 });
  tl.fromTo(
    hueco,
    { strokeOpacity: 0.4 },
    { strokeOpacity: 1, duration: LATIDO_S / factor, repeat: LATIDOS * 2 - 1, yoyo: true, ease: "sine.inOut" },
  );

  // 2. Espera a la imagen (si ya cargó, sigue de inmediato).
  tl.add(() => {
    tl.pause();
    void esperarCarga(img).then(() => tl.resume());
  });

  // 3. Revelado: la foto se asienta y la barra de luz la cruza.
  barra = document.createElementNS(ns, "rect");
  barra.setAttribute("x", String(x));
  barra.setAttribute("y", String(y));
  barra.setAttribute("width", String(ANCHO_BARRA));
  barra.setAttribute("height", String(alto));
  barra.setAttribute("fill", "#F8FAFC");
  barra.setAttribute("opacity", "0");
  barra.setAttribute("pointer-events", "none");
  grupo.appendChild(barra);
  const barraEl = barra;

  tl.to(img, { opacity: 1, scale: 1, filter: "blur(0px) brightness(1)", duration: REVELADO_S / factor, ease: "power2.out" });
  // Dos pasadas de la barra de luz por el hueco, de izquierda a derecha.
  tl.fromTo(
    barraEl,
    { x: -ANCHO_BARRA, opacity: 0.6 },
    { x: ancho, opacity: 0, duration: BARRIDO_S / factor, ease: "power1.inOut" },
    "<",
  );
  tl.fromTo(
    barraEl,
    { x: -ANCHO_BARRA, opacity: 0.4 },
    { x: ancho, opacity: 0, duration: BARRIDO_S / factor, ease: "power1.inOut" },
    `<+=${SEGUNDO_BARRIDO_DESDE_S / factor}`,
  );

  // 4. Un respiro con la etiqueta y se retira.
  tl.to({}, { duration: PAUSA_FINAL_S / factor });
  tl.to(etiqueta, { opacity: 0, duration: DESVANECER_S / factor });
  return { timeline: tl, restaurar };
}
