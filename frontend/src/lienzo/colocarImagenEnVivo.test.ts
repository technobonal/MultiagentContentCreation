// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { crearEstadoInicial } from "../timeline/reducer.ts";
import type { Estado } from "../timeline/types.ts";
import { colocarImagenEnVivo, imagenesColocadas, imagenNueva, radioDeHueco } from "./colocarImagenEnVivo.ts";

const IMG = { licencia: "L", texto_alternativo: "t" };

function estadoCon(imagenes: Estado["lienzo"]["imagenes"]): Estado {
  const base = crearEstadoInicial();
  return { ...base, lienzo: { ...base.lienzo, imagenes } };
}

describe("imagenesColocadas e imagenNueva", () => {
  it("lista las imágenes por «slide:campo»", () => {
    const e = estadoCon({ 1: { imagen_portada: { ...IMG, referencia: "foto-1" } }, 2: { imagen_producto: { ...IMG, referencia: "foto-2" } } });
    expect([...imagenesColocadas(e)]).toEqual([["1:imagen_portada", "foto-1"], ["2:imagen_producto", "foto-2"]]);
  });

  it("detecta la imagen nueva del slide activo y nada más", () => {
    const antes = new Map([["1:imagen_portada", "foto-1"]]);
    const ahora = new Map([["1:imagen_portada", "foto-1"], ["2:imagen_producto", "foto-2"]]);
    expect(imagenNueva(antes, ahora, 2)).toEqual({ slide: 2, campo: "imagen_producto" });
    expect(imagenNueva(antes, ahora, 1)).toBeNull(); // la nueva es de otro slide
    expect(imagenNueva(ahora, ahora, 2)).toBeNull(); // nada cambió
  });

  it("una referencia distinta en el mismo campo cuenta como nueva", () => {
    const antes = new Map([["2:imagen_producto", "foto-2"]]);
    expect(imagenNueva(antes, new Map([["2:imagen_producto", "foto-9"]]), 2)).toEqual({ slide: 2, campo: "imagen_producto" });
  });

  it("sin imágenes no hay nada nuevo", () => {
    expect(imagenNueva(new Map(), imagenesColocadas(estadoCon({})), 1)).toBeNull();
  });
});

/** Mide un elemento a la fuerza: el DOM simulado no hace layout y todo mediría 0. */
function medir(el: Element, left: number, top: number, width: number, height: number): void {
  (el as unknown as { getBoundingClientRect: () => DOMRect }).getBoundingClientRect = () =>
    ({ left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) }) as DOMRect;
}

function montar(conTamano = true) {
  const marco = document.createElement("div");
  marco.innerHTML = `<svg><g data-campo="{{imagen_producto}}">
      <rect x="80" y="698" width="920" height="422"/>
      <image x="80" y="698" width="920" height="422" data-cargada="true" href="/api/runs/r/imagenes/foto-2"/>
    </g></svg>
    <div class="avatar" data-agente="director_arte"><div class="avatar-cuerpo"><svg class="cara"></svg></div></div>`;
  document.body.appendChild(marco);
  const grupo = marco.querySelector("g") as unknown as SVGElement;
  const img = marco.querySelector("image") as unknown as SVGImageElement;
  if (conTamano) {
    medir(marco, 0, 0, 540, 675);
    medir(marco.querySelector("rect") as Element, 40, 349, 460, 211);
    medir(marco.querySelector(".avatar") as Element, 10, 620, 44, 44);
  }
  return { marco, grupo, img };
}

const OPCIONES = { agente: "director_arte", nombreAgente: "Director de arte", descripcion: "Imagen de la página 3 de la fuente", slide: 2 };

describe("colocarImagenEnVivo", () => {
  it("monta la escena: el avatar copiado con la foto en las manos, foco, onda, destello y cartel", () => {
    const { marco, grupo, img } = montar();
    const { restaurar } = colocarImagenEnVivo({ grupo, marco, ...OPCIONES });
    const escena = marco.querySelector(".foto-escena") as HTMLElement;
    expect(escena).not.toBeNull();
    for (const clase of [".foto-foco", ".foto-onda", ".foto-flash", ".foto-tarjeta", ".foto-portador", ".foto-cartel"]) {
      expect(escena.querySelector(clase), clase).not.toBeNull();
    }
    expect(escena.querySelector(".foto-cartel-agente")?.textContent).toBe("Director de arte");
    // El que lleva la foto es una copia del avatar del agente (el real lo mueve AvataresVivos).
    expect(escena.querySelector(".foto-portador .avatar-cuerpo svg.cara")).not.toBeNull();
    expect((escena.querySelector(".foto-tarjeta-img") as HTMLImageElement).getAttribute("src")).toBe("/api/runs/r/imagenes/foto-2");
    // La foto real queda oculta hasta el aterrizaje y el fundido CSS no compite con GSAP.
    expect(img.style.opacity).toBe("0");
    expect(img.style.transition).toBe("none");
    restaurar();
  });

  it("restaurar quita la escena, vuelve a mostrar el avatar real y devuelve la foto al CSS; una segunda vez no falla", () => {
    const { marco, grupo, img } = montar();
    const { restaurar } = colocarImagenEnVivo({ grupo, marco, ...OPCIONES });
    const avatar = marco.querySelector(".avatar") as HTMLElement;
    avatar.style.visibility = "hidden"; // como lo deja la escena mientras su copia trabaja
    restaurar();
    expect(avatar.style.visibility).toBe("");
    expect(marco.querySelector(".foto-escena")).toBeNull();
    expect(img.style.opacity).toBe("");
    expect(img.style.transition).toBe("");
    expect(() => restaurar()).not.toThrow();
  });

  it("si un hueco no se ve (medida 0) no monta nada y no toca la imagen", () => {
    const { marco, grupo, img } = montar(false);
    const { restaurar } = colocarImagenEnVivo({ grupo, marco, ...OPCIONES });
    expect(marco.querySelector(".foto-escena")).toBeNull();
    expect(img.style.opacity).toBe("");
    expect(() => restaurar()).not.toThrow();
  });

  it("sin <image> no falla", () => {
    const marco = document.createElement("div");
    marco.innerHTML = `<svg><g data-campo="{{x}}"></g></svg>`;
    const grupo = marco.querySelector("g") as unknown as SVGElement;
    expect(() => colocarImagenEnVivo({ grupo, marco, ...OPCIONES }).restaurar()).not.toThrow();
  });
});

// El backend deja FOTOS_PAUSA_SEG (3,5 s) entre foto y foto, y un evento nuevo corta la escena en curso:
// a 1x tiene que caber con margen, pero ser lo bastante larga para que el ojo la note.
const PAUSA_DEL_BACKEND_S = 3.5;

describe("duración de la escena", () => {
  it("a 1x dura entre 2,6 s y la pausa del backend menos un margen", () => {
    const { marco, grupo } = montar();
    const { timeline, restaurar } = colocarImagenEnVivo({ grupo, marco, ...OPCIONES, velocidad: 1 });
    expect(timeline.duration()).toBeGreaterThan(2.6);
    expect(timeline.duration()).toBeLessThan(PAUSA_DEL_BACKEND_S - 0.2);
    restaurar();
  });

  it("a 2x dura la mitad", () => {
    const uno = montar();
    const a = colocarImagenEnVivo({ grupo: uno.grupo, marco: uno.marco, ...OPCIONES, velocidad: 1 });
    const dos = montar();
    const b = colocarImagenEnVivo({ grupo: dos.grupo, marco: dos.marco, ...OPCIONES, velocidad: 2 });
    expect(b.timeline.duration()).toBeCloseTo(a.timeline.duration() / 2, 1);
    a.restaurar();
    b.restaurar();
  });
});

describe("sin avatar en el marco", () => {
  it("la escena igual funciona (el portador sale vacío desde la esquina)", () => {
    const { marco, grupo } = montar();
    marco.querySelector(".avatar")?.remove();
    const { timeline, restaurar } = colocarImagenEnVivo({ grupo, marco, ...OPCIONES });
    expect(marco.querySelector(".foto-portador")).not.toBeNull();
    expect(timeline.duration()).toBeGreaterThan(2.6);
    restaurar();
  });
});

describe("la forma del hueco", () => {
  function contorno(atributos: Record<string, string>): Element {
    const el = document.createElement("rect");
    for (const [k, v] of Object.entries(atributos)) el.setAttribute(k, v);
    return el;
  }

  it("usa el redondeo declarado (arcos y círculos)", () => {
    expect(radioDeHueco(contorno({ "data-radio": "50% 50% 0 0 / 64% 64% 0 0", rx: "5" }))).toBe("50% 50% 0 0 / 64% 64% 0 0");
  });

  it("sin declararlo, lo saca del rx del rectángulo, en porcentajes y sin pasar del 50 %", () => {
    expect(radioDeHueco(contorno({ rx: "16", width: "920", height: "422" }))).toBe("1.7% / 3.8%");
    expect(radioDeHueco(contorno({ rx: "300", width: "400", height: "400" }))).toBe("50% / 50%");
  });

  it("sin nada que imitar no devuelve redondeo", () => {
    expect(radioDeHueco(contorno({ width: "920", height: "422" }))).toBe("");
    expect(radioDeHueco(contorno({}))).toBe("");
  });

  it("la foto en las manos, el foco y la onda toman esa forma", () => {
    const { marco, grupo } = montar();
    (marco.querySelector("rect") as Element).setAttribute("data-radio", "50%");
    const { restaurar } = colocarImagenEnVivo({ grupo, marco, ...OPCIONES });
    for (const clase of [".foto-tarjeta", ".foto-foco", ".foto-onda"]) {
      expect((marco.querySelector(clase) as HTMLElement).style.borderRadius, clase).toBe("50%");
    }
    restaurar();
  });
});
