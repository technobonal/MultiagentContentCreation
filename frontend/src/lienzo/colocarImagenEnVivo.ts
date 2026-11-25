// ---------------------------------------------------------------------------
// colocarImagenEnVivo.ts — Escena del director de arte al colocar una foto en un hueco de la plantilla. Es grande a
// propósito: el avatar mide 44 px y un borde que late no se nota, así que la acción se cuenta con elementos visibles.
//  1. RECORTANDO: destello de cámara; la foto aparece grande al centro con un marco de recorte que se cierra y una línea
//     de escaneo, y un cartel dice qué hace el agente.
//  2. COLOCANDO: el resto del lienzo se oscurece (foco sobre el hueco) y la foto VUELA hasta él.
//  3. ATERRIZAJE: onda de impacto y destello; el cartel pasa a «Foto colocada».
// Se espera a que la imagen cargue antes de empezar. Las partes puras (qué foto es nueva) están aparte para probarlas.
// ---------------------------------------------------------------------------
import gsap from "gsap";
import type { Estado } from "../timeline/types.ts";

// Duraciones base (s, a 1x; se dividen por la velocidad). La suma (~3 s) tiene que caber en la pausa que el backend deja
// entre foto y foto (`FOTOS_PAUSA_SEG`, 3,5 s): un evento nuevo corta la escena en curso.
const FLASH_S = 0.3;
const APARECER_S = 0.5;
const ESCANEO_S = 0.8; // el marco de recorte se cierra y la línea de escaneo baja
const PAUSA_ANTES_VUELO_S = 0.15;
const FOCO_S = 0.3;
const VUELO_S = 0.9;
const ATERRIZAJE_S = 0.7; // onda y destello
const SALIDA_S = 0.35;
const CARTEL_S = 0.25;
// Ancho de la tarjeta al centro, como fracción del ancho del marco.
const FRACCION_TARJETA = 0.5;
// Un hueco que mide menos que esto (por ejemplo, oculto) no se anima.
const TAMANO_MINIMO_PX = 4;
// Si la imagen tarda más que esto en cargar, se anima igual (se verá el hueco o el error).
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
  /** Contenedor del lienzo (posición relativa): sobre él se monta la escena. */
  readonly marco: HTMLElement;
  readonly nombreAgente: string;
  /** Qué foto es (el texto alternativo trae la página de origen). */
  readonly descripcion: string;
  /** Número de slide donde se coloca. */
  readonly slide: number;
  readonly velocidad?: number;
}

export interface ColocacionEnVivo {
  readonly timeline: gsap.core.Timeline;
  /** Deja el hueco y el lienzo como si no hubiera escena (al cortarla por un evento nuevo o al terminar). Idempotente. */
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

function crear(clase: string, padre: HTMLElement, etiqueta = "div"): HTMLElement {
  const el = document.createElement(etiqueta);
  el.className = clase;
  padre.appendChild(el);
  return el;
}

export function colocarImagenEnVivo(o: OpcionesColocacion): ColocacionEnVivo {
  const { grupo, marco, nombreAgente, descripcion, slide } = o;
  const factor = Math.max(0.1, o.velocidad ?? 1);
  const img = grupo.querySelector<SVGImageElement>("image");
  const hueco = grupo.querySelector<SVGElement>("rect");
  const rHueco = (hueco ?? grupo).getBoundingClientRect();
  const tl = gsap.timeline();

  // Sin imagen o sin un hueco visible no hay nada que animar (por ejemplo, un slide oculto).
  if (!img || !hueco || rHueco.width < TAMANO_MINIMO_PX || rHueco.height < TAMANO_MINIMO_PX) {
    tl.to({}, { duration: 0.01 });
    return { timeline: tl, restaurar: () => undefined };
  }

  const escena = crear("foto-escena", marco);
  escena.setAttribute("aria-hidden", "true");

  function restaurar(): void {
    gsap.killTweensOf(escena.querySelectorAll("*"));
    escena.remove();
    if (img) {
      gsap.killTweensOf(img);
      // Se devuelve el control al CSS (visible cuando cargó) y se quita todo lo que puso la escena.
      img.style.removeProperty("transition");
      gsap.set(img, { clearProps: "opacity,transform,filter,transformOrigin" });
    }
  }
  tl.eventCallback("onComplete", restaurar);

  // La foto real queda oculta hasta el aterrizaje; el fundido CSS se apaga mientras GSAP manda.
  img.style.transition = "none";
  gsap.set(img, { opacity: 0 });

  const rMarco = marco.getBoundingClientRect();
  const hx = rHueco.left - rMarco.left;
  const hy = rHueco.top - rMarco.top;
  const proporcion = rHueco.width / rHueco.height;

  // Elementos de la escena.
  const foco = crear("foto-foco", escena); // oscurece todo menos el hueco (box-shadow enorme)
  const onda = crear("foto-onda", escena);
  const flash = crear("foto-flash", escena);
  const tarjeta = crear("foto-tarjeta", escena);
  const foto = document.createElement("img");
  foto.className = "foto-tarjeta-img";
  foto.alt = "";
  foto.src = img.getAttribute("href") ?? "";
  tarjeta.appendChild(foto);
  const recorte = crear("foto-recorte", tarjeta);
  const linea = crear("foto-escaneo", tarjeta);
  const cartel = crear("foto-cartel", escena);
  const cartelAgente = crear("foto-cartel-agente", cartel, "span");
  cartelAgente.textContent = nombreAgente;
  const cartelTexto = crear("foto-cartel-texto", cartel, "span");

  // Posiciones: el foco y la onda coinciden con el hueco; la tarjeta empieza grande al centro.
  for (const el of [foco, onda]) gsap.set(el, { left: hx, top: hy, width: rHueco.width, height: rHueco.height });
  const anchoInicial = Math.max(rHueco.width, rMarco.width * FRACCION_TARJETA);
  const altoInicial = anchoInicial / proporcion;
  gsap.set(tarjeta, {
    left: (rMarco.width - anchoInicial) / 2,
    top: (rMarco.height - altoInicial) / 2 - 24,
    width: anchoInicial,
    height: altoInicial,
    opacity: 0,
    scale: 0.55,
    rotation: -7,
  });
  gsap.set([foco, onda, flash], { opacity: 0 });
  gsap.set(cartel, { opacity: 0, y: -18 });
  gsap.set(recorte, { inset: "-9%" });
  gsap.set(linea, { top: "0%", opacity: 0 });

  // 0. Espera a la imagen (si ya cargó, sigue de inmediato).
  tl.add(() => {
    tl.pause();
    void esperarCarga(img).then(() => tl.resume());
  }, 0);

  // 1. RECORTANDO: destello, la tarjeta aparece con rebote, el marco se cierra y la línea escanea.
  const aparecer = APARECER_S / factor;
  const escaneo = ESCANEO_S / factor;
  tl.add(() => {
    cartelTexto.textContent = `Recortando · ${descripcion}`;
  }, 0.01);
  tl.to(cartel, { opacity: 1, y: 0, duration: CARTEL_S / factor, ease: "power2.out" }, 0.01);
  tl.fromTo(flash, { opacity: 0.85 }, { opacity: 0, duration: FLASH_S / factor, ease: "power2.out" }, 0.01);
  tl.to(tarjeta, { opacity: 1, scale: 1, rotation: -3, duration: aparecer, ease: "back.out(1.8)" }, 0.01);
  tl.to(recorte, { inset: "0%", duration: escaneo, ease: "power2.inOut" }, aparecer);
  tl.fromTo(linea, { top: "0%", opacity: 1 }, { top: "100%", duration: escaneo, ease: "none" }, aparecer);
  tl.to(linea, { opacity: 0, duration: 0.1 / factor }, aparecer + escaneo);

  // 2. COLOCANDO: el foco oscurece el resto y la foto vuela al hueco.
  const t2 = aparecer + escaneo + PAUSA_ANTES_VUELO_S / factor;
  tl.add(() => {
    cartelTexto.textContent = `Colocando en el slide ${slide}`;
  }, t2);
  tl.to(foco, { opacity: 1, duration: FOCO_S / factor }, t2);
  tl.to(
    tarjeta,
    { left: hx, top: hy, width: rHueco.width, height: rHueco.height, rotation: 0, duration: VUELO_S / factor, ease: "power3.inOut" },
    t2,
  );

  // 3. ATERRIZAJE: la foto real aparece bajo la tarjeta, onda de impacto y destello.
  const t3 = t2 + VUELO_S / factor;
  tl.set(img, { opacity: 1 }, t3);
  tl.add(() => {
    cartelTexto.textContent = "Foto colocada ✓";
  }, t3);
  tl.fromTo(onda, { opacity: 0.95, scale: 1 }, { opacity: 0, scale: 1.18, duration: ATERRIZAJE_S / factor, ease: "power2.out" }, t3);
  tl.fromTo(flash, { opacity: 0.45 }, { opacity: 0, duration: 0.35 / factor, ease: "power2.out" }, t3);
  tl.to(tarjeta, { opacity: 0, duration: 0.3 / factor }, t3 + 0.05 / factor);

  // 4. Salida: el foco y el cartel se retiran.
  const t4 = t3 + 0.45 / factor; // se solapa con el final de la onda
  tl.to(foco, { opacity: 0, duration: SALIDA_S / factor }, t4);
  tl.to(cartel, { opacity: 0, y: -10, duration: SALIDA_S / factor }, t4);
  return { timeline: tl, restaurar };
}
