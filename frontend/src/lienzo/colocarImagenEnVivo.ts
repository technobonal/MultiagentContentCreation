// ---------------------------------------------------------------------------
// colocarImagenEnVivo.ts — Escena del director de arte colocando una foto: EL AVATAR LA LLEVA.
//  1. TOMA LA FOTO: el avatar del agente se agranda en su lugar y la foto aparece en sus manos.
//  2. LA LLEVA: vuela con ella en una curva hasta encima del hueco; el resto del lienzo se oscurece.
//  3. LA COLOCA: la foto se despega de sus manos y se ajusta al hueco con un rebote; el avatar empuja.
//  4. SE VA: onda de impacto, «Foto colocada ✓», y el avatar vuelve a su tamaño y se desvanece.
// Se usa una COPIA del avatar (el real lo mueve AvataresVivos cuadro a cuadro y pisaría cualquier transform); el real
// queda oculto durante la escena para que no se vean dos. Avatar y foto viajan juntos porque se animan con los mismos
// tiempos y la misma curva. Las partes puras (qué foto es nueva) están aparte para probarlas sin DOM.
// ---------------------------------------------------------------------------
import gsap from "gsap";
import type { Estado } from "../timeline/types.ts";

// Duraciones base (s, a 1x; se dividen por la velocidad). La suma (~3 s) tiene que caber en la pausa que el backend deja
// entre foto y foto (`FOTOS_PAUSA_SEG`, 3,5 s): un evento nuevo corta la escena en curso.
const TOMAR_S = 0.45; // el avatar crece y la foto aparece en sus manos
const LEVANTAR_S = 0.3; // gesto de levantar la foto antes de salir
const VUELO_S = 1.1;
const COLOCAR_S = 0.55;
const ONDA_S = 0.65;
const SALIDA_DESDE_S = 0.2; // tras colocar, el avatar empieza a irse así de tarde
const SALIDA_S = 0.45;
const CARTEL_S = 0.25;
const FOCO_S = 0.35;
// Tamaño del avatar en reposo (px, como .avatar en style.css) y cuánto crece al trabajar: hasta 2,4 veces, pero nunca
// más que una fracción del ancho del lienzo (en un lienzo chico un avatar de 105 px tapaba todo y se salía del borde).
const TAM_AVATAR = 44;
const ESCALA_AVATAR_MAX = 2.4;
const ESCALA_AVATAR_MIN = 1.6;
const FRACCION_AVATAR = 0.17;
// Margen superior que se deja libre para el cartel (px): el avatar ni su arco de vuelo entran ahí.
const MARGEN_CARTEL_PX = 68;
// Altura del arco del vuelo (px hacia arriba en el punto medio).
const ARCO_PX = 70;
// Ancho de la foto en las manos: fracción del ancho del hueco, acotada.
const FRACCION_FOTO_EN_MANOS = 0.42;
const FOTO_EN_MANOS_MIN_PX = 110;
const FOTO_EN_MANOS_MAX_PX = 240;
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

/**
 * Redondeo CSS que imita la forma del hueco, en porcentajes para que valga a cualquier tamaño (la foto cambia de tamaño
 * mientras vuela). Manda `data-radio` (formas que no son un rectángulo: arcos y círculos); si no está, sale del `rx` del
 * rectángulo; "" si no hay nada que imitar (queda el redondeo de la hoja de estilos).
 */
export function radioDeHueco(hueco: Element): string {
  const declarado = hueco.getAttribute("data-radio");
  if (declarado) return declarado;
  const rx = Number(hueco.getAttribute("rx"));
  const ancho = Number(hueco.getAttribute("width"));
  const alto = Number(hueco.getAttribute("height"));
  if (!(rx > 0 && ancho > 0 && alto > 0)) return "";
  const porciento = (medida: number) => `${Math.min(50, Math.round((rx / medida) * 1000) / 10)}%`;
  return `${porciento(ancho)} / ${porciento(alto)}`;
}

export interface OpcionesColocacion {
  /** Grupo `[data-campo]` del hueco de imagen (trae el rect punteado y el <image>). */
  readonly grupo: SVGElement;
  /** Contenedor del lienzo (posición relativa): sobre él se monta la escena y en él viven los avatares. */
  readonly marco: HTMLElement;
  /** Agente que coloca la foto (para encontrar su avatar). */
  readonly agente?: string;
  readonly nombreAgente: string;
  /** Oficio que ejerce al colocarla; si viene, el cartel lo muestra junto al nombre. */
  readonly especialidad?: string;
  /** Qué foto es (el texto alternativo trae la página de origen). */
  readonly descripcion: string;
  /** Número de slide donde se coloca. */
  readonly slide: number;
  readonly velocidad?: number;
}

export interface ColocacionEnVivo {
  readonly timeline: gsap.core.Timeline;
  /** Deja el hueco, el avatar y el lienzo como si no hubiera escena (al cortarla o al terminar). Idempotente. */
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

/** «Página N» a partir del texto alternativo («Imagen de la página 3 de la fuente»), o el texto entero si no la trae. */
function origenCorto(descripcion: string): string {
  const m = /p[aá]gina\s+(\d+)/i.exec(descripcion);
  return m ? `la foto de la página ${m[1]}` : descripcion;
}

export function colocarImagenEnVivo(o: OpcionesColocacion): ColocacionEnVivo {
  const { grupo, marco, nombreAgente, descripcion, slide } = o;
  const factor = Math.max(0.1, o.velocidad ?? 1);
  const img = grupo.querySelector<SVGImageElement>("image");
  const hueco = grupo.querySelector<SVGElement>(".hueco-forma, rect");
  const rHueco = (hueco ?? grupo).getBoundingClientRect();
  const tl = gsap.timeline();

  // Sin imagen o sin un hueco visible no hay nada que animar (por ejemplo, un slide oculto).
  if (!img || !hueco || rHueco.width < TAMANO_MINIMO_PX || rHueco.height < TAMANO_MINIMO_PX) {
    tl.to({}, { duration: 0.01 });
    return { timeline: tl, restaurar: () => undefined };
  }

  const escena = crear("foto-escena", marco);
  escena.setAttribute("aria-hidden", "true");
  const avatarReal = marco.querySelector<HTMLElement>(`.avatar[data-agente="${o.agente ?? "director_arte"}"]`);

  function restaurar(): void {
    gsap.killTweensOf(escena.querySelectorAll("*"));
    escena.remove();
    if (avatarReal) avatarReal.style.removeProperty("visibility");
    if (img) {
      gsap.killTweensOf(img);
      // Se devuelve el control al CSS (visible cuando cargó) y se quita todo lo que puso la escena.
      img.style.removeProperty("transition");
      gsap.set(img, { clearProps: "opacity,transform,filter,transformOrigin" });
    }
  }
  tl.eventCallback("onComplete", restaurar);

  // La foto real queda oculta hasta que el avatar la coloca; el fundido CSS se apaga mientras GSAP manda.
  img.style.transition = "none";
  gsap.set(img, { opacity: 0 });

  // --- Geometría (px, relativa al marco) ---
  const rMarco = marco.getBoundingClientRect();
  const hx = rHueco.left - rMarco.left;
  const hy = rHueco.top - rMarco.top;
  const proporcion = rHueco.width / rHueco.height;
  const escalaAvatar = Math.min(ESCALA_AVATAR_MAX, Math.max(ESCALA_AVATAR_MIN, (rMarco.width * FRACCION_AVATAR) / TAM_AVATAR));
  const lado = TAM_AVATAR * escalaAvatar; // tamaño visible del avatar agrandado
  // Foto en las manos.
  const fw = Math.min(FOTO_EN_MANOS_MAX_PX, Math.max(FOTO_EN_MANOS_MIN_PX, rHueco.width * FRACCION_FOTO_EN_MANOS));
  const fh = fw / proporcion;
  // Dónde sostiene la foto respecto del CENTRO del avatar: abajo y un poco a la derecha, tapada en parte por las manos.
  const manosX = -fw * 0.2;
  const manosY = lado * 0.22;
  // Centro del avatar acotado para que él y la foto en sus manos queden DENTRO del lienzo y bajo el cartel
  // (el avatar real puede estar en una esquina, por ejemplo tras pintar el fondo, y la escena empezaba cortada).
  const acotarX = (cx: number) => Math.min(rMarco.width - Math.max(lado / 2, fw + manosX) - 4, Math.max(lado / 2 + 4, cx));
  const acotarY = (cy: number) => Math.min(rMarco.height - (manosY + fh) - 4, Math.max(MARGEN_CARTEL_PX + lado / 2, cy));
  // Origen: el avatar real (o, si no está, abajo a la izquierda), siempre dentro del lienzo.
  let cx0 = TAM_AVATAR;
  let cy0 = rMarco.height - TAM_AVATAR;
  if (avatarReal) {
    const r = avatarReal.getBoundingClientRect();
    if (r.width > 0) {
      cx0 = r.left - rMarco.left + r.width / 2;
      cy0 = r.top - rMarco.top + r.height / 2;
    }
  }
  cx0 = acotarX(cx0);
  cy0 = acotarY(cy0);
  // Destino: el avatar queda encima del hueco y la foto, justo sobre su borde superior.
  const cx1 = acotarX(hx + rHueco.width / 2 - manosX - fw / 2);
  const cy1 = acotarY(hy - manosY - fh + 6);

  // --- Elementos (el orden es el de apilado: lo último queda arriba) ---
  const foco = crear("foto-foco", escena); // oscurece todo menos el hueco
  const onda = crear("foto-onda", escena);
  const tarjeta = crear("foto-tarjeta", escena);
  const foto = document.createElement("img");
  foto.className = "foto-tarjeta-img";
  foto.alt = "";
  foto.src = img.getAttribute("href") ?? "";
  tarjeta.appendChild(foto);
  const portador = crear("foto-portador", escena); // la copia del avatar
  const cuerpo = avatarReal?.querySelector(".avatar-cuerpo");
  if (cuerpo) portador.innerHTML = cuerpo.outerHTML;
  const flash = crear("foto-flash", escena);
  const cartel = crear("foto-cartel", escena);
  const cartelAgente = crear("foto-cartel-agente", cartel, "span");
  cartelAgente.textContent = o.especialidad ? `${nombreAgente} · ${o.especialidad}` : nombreAgente;
  const cartelTexto = crear("foto-cartel-texto", cartel, "span");

  // La foto en las manos, el foco y la onda toman la forma del hueco (píldora, arco, círculo o esquinas redondeadas).
  const radio = radioDeHueco(hueco);
  if (radio) for (const el of [foco, onda, tarjeta]) el.style.borderRadius = radio;

  // Posición de la foto en las manos para un centro de avatar dado.
  const enManos = (cx: number, cy: number) => ({ left: cx + manosX, top: cy + manosY });

  for (const el of [foco, onda]) gsap.set(el, { left: hx, top: hy, width: rHueco.width, height: rHueco.height, opacity: 0 });
  gsap.set(flash, { opacity: 0 });
  gsap.set(portador, { left: cx0 - TAM_AVATAR / 2, top: cy0 - TAM_AVATAR / 2, scale: 1, transformOrigin: "50% 50%", opacity: 1 });
  gsap.set(tarjeta, { ...enManos(cx0, cy0), width: fw, height: fh, rotation: -8, scale: 0, transformOrigin: "50% 0%", opacity: 1 });
  gsap.set(cartel, { opacity: 0, y: -18 });

  // 0. Espera a la imagen (si ya cargó, sigue de inmediato) y oculta el avatar real.
  tl.add(() => {
    if (avatarReal) avatarReal.style.visibility = "hidden";
    tl.pause();
    void esperarCarga(img).then(() => tl.resume());
  }, 0);

  // 1. TOMA LA FOTO: el avatar crece y la foto aparece en sus manos.
  const tomar = TOMAR_S / factor;
  tl.add(() => {
    cartelTexto.textContent = `Tomando ${origenCorto(descripcion)}`;
  }, 0.01);
  tl.to(cartel, { opacity: 1, y: 0, duration: CARTEL_S / factor, ease: "power2.out" }, 0.01);
  tl.to(portador, { scale: escalaAvatar, duration: tomar, ease: "back.out(2)" }, 0.01);
  tl.to(tarjeta, { scale: 1, duration: tomar, ease: "back.out(1.6)" }, 0.01 + tomar * 0.4);
  // Gesto de levantar la foto (los dos suben y bajan juntos).
  const levantar = LEVANTAR_S / factor;
  const gesto = Math.max(0, Math.min(14, cy0 - lado / 2 - MARGEN_CARTEL_PX));
  tl.to([portador, tarjeta], { y: -gesto, duration: levantar / 2, ease: "sine.out" }, tomar);
  tl.to([portador, tarjeta], { y: 0, duration: levantar / 2, ease: "sine.in" }, tomar + levantar / 2);

  // 2. LA LLEVA: mismo recorrido para avatar y foto (así viajan juntos) y un arco hacia arriba.
  const t2 = tomar + levantar;
  const vuelo = VUELO_S / factor;
  tl.add(() => {
    cartelTexto.textContent = `Llevándola al slide ${slide}`;
  }, t2);
  tl.to(foco, { opacity: 1, duration: FOCO_S / factor }, t2);
  tl.to(portador, { left: cx1 - TAM_AVATAR / 2, top: cy1 - TAM_AVATAR / 2, duration: vuelo, ease: "power2.inOut" }, t2);
  tl.to(tarjeta, { ...enManos(cx1, cy1), rotation: -4, duration: vuelo, ease: "power2.inOut" }, t2);
  // El arco no puede subir al avatar hasta el cartel (en huecos de la parte de arriba casi no hay arco).
  const arco = Math.max(0, Math.min(ARCO_PX, Math.min(cy0, cy1) - lado / 2 - MARGEN_CARTEL_PX));
  tl.to([portador, tarjeta], { y: -arco, duration: vuelo / 2, ease: "sine.out" }, t2);
  tl.to([portador, tarjeta], { y: 0, duration: vuelo / 2, ease: "sine.in" }, t2 + vuelo / 2);

  // 3. LA COLOCA: la foto se despega de las manos y llena el hueco con un rebote; el avatar empuja.
  const t3 = t2 + vuelo;
  const colocar = COLOCAR_S / factor;
  tl.add(() => {
    cartelTexto.textContent = `Colocándola en el slide ${slide}`;
  }, t3);
  tl.to(
    tarjeta,
    { left: hx, top: hy, width: rHueco.width, height: rHueco.height, rotation: 0, transformOrigin: "50% 50%", duration: colocar, ease: "back.out(1.2)" },
    t3,
  );
  tl.to(portador, { y: 12, rotation: 8, duration: colocar / 2, ease: "power1.out" }, t3);
  tl.to(portador, { y: 0, rotation: 0, duration: colocar / 2, ease: "power1.in" }, t3 + colocar / 2);

  // 4. ATERRIZAJE Y SALIDA: aparece la foto real, onda y destello; el avatar se achica y se va.
  const t4 = t3 + colocar;
  tl.set(img, { opacity: 1 }, t4);
  tl.add(() => {
    cartelTexto.textContent = "Foto colocada ✓";
  }, t4);
  tl.fromTo(onda, { opacity: 0.95, scale: 1 }, { opacity: 0, scale: 1.15, duration: ONDA_S / factor, ease: "power2.out" }, t4);
  tl.fromTo(flash, { opacity: 0.35 }, { opacity: 0, duration: 0.3 / factor, ease: "power2.out" }, t4);
  tl.to(tarjeta, { opacity: 0, duration: 0.25 / factor }, t4 + 0.05 / factor);
  const t5 = t4 + SALIDA_DESDE_S / factor;
  const salida = SALIDA_S / factor;
  tl.to(portador, { scale: 1, opacity: 0, duration: salida, ease: "power2.in" }, t5);
  tl.to(foco, { opacity: 0, duration: salida }, t5);
  tl.to(cartel, { opacity: 0, y: -10, duration: salida }, t5);
  return { timeline: tl, restaurar };
}
