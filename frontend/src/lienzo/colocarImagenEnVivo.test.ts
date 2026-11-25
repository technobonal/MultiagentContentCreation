// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { crearEstadoInicial } from "../timeline/reducer.ts";
import type { Estado } from "../timeline/types.ts";
import { colocarImagenEnVivo, imagenesColocadas, imagenNueva } from "./colocarImagenEnVivo.ts";

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

function montar() {
  const marco = document.createElement("div");
  marco.innerHTML = `<svg><g data-campo="{{imagen_producto}}">
      <rect x="80" y="698" width="920" height="422" stroke-opacity=".5"/>
      <image x="80" y="698" width="920" height="422" data-cargada="true"/>
    </g></svg><span class="etiqueta"></span>`;
  document.body.appendChild(marco);
  const grupo = marco.querySelector("g") as unknown as SVGElement;
  const etiqueta = marco.querySelector(".etiqueta") as HTMLElement;
  const img = marco.querySelector("image") as unknown as SVGImageElement;
  return { marco, grupo, etiqueta, img };
}

describe("colocarImagenEnVivo", () => {
  it("al empezar oculta la foto, muestra la etiqueta con el agente y agrega la barra de luz", () => {
    const { marco, grupo, etiqueta, img } = montar();
    const { restaurar } = colocarImagenEnVivo({ grupo, etiqueta, marco, nombreAgente: "Director de arte" });
    expect(etiqueta.textContent).toBe("Director de arte");
    expect(img.style.opacity).toBe("0");
    expect(img.style.transition).toBe("none"); // el fundido CSS no compite con GSAP
    expect(grupo.querySelectorAll("rect").length).toBe(2); // el hueco y la barra
    restaurar();
  });

  it("restaurar devuelve el hueco al CSS: sin estilos de la animación y sin la barra", () => {
    const { marco, grupo, etiqueta, img } = montar();
    const { restaurar } = colocarImagenEnVivo({ grupo, etiqueta, marco, nombreAgente: "Director de arte" });
    restaurar();
    expect(img.style.opacity).toBe("");
    expect(img.style.filter).toBe("");
    expect(img.style.transition).toBe("");
    expect(grupo.querySelectorAll("rect").length).toBe(1);
    expect(etiqueta.style.opacity).toBe("0");
    restaurar(); // idempotente: no falla la segunda vez
  });

  it("sin <image> o sin hueco no falla y no deja nada a medias", () => {
    const marco = document.createElement("div");
    marco.innerHTML = `<svg><g data-campo="{{x}}"></g></svg><span></span>`;
    const grupo = marco.querySelector("g") as unknown as SVGElement;
    const etiqueta = marco.querySelector("span") as HTMLElement;
    expect(() => colocarImagenEnVivo({ grupo, etiqueta, marco, nombreAgente: "A" }).restaurar()).not.toThrow();
  });
});
