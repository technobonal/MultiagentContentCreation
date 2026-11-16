// ---------------------------------------------------------------------------
// resaltado.ts — Subraya en el slide la afirmación que el revisor acaba de revisar.
// Trabaja sobre el DOM ya pintado: parte el texto de un campo en tres trozos
// (antes, <mark>, después). Se repinta limpio en cada cambio de estado.
// ---------------------------------------------------------------------------
import { localizarAfirmacion } from "./revisor.ts";
import type { TonoTarjeta } from "./revisor.ts";

// Subraya la afirmación en el primer campo del slide que la contenga.
// `animada` activa el barrido de entrada. Devuelve true si encontró dónde subrayar.
export function resaltarAfirmacion(
  raiz: ParentNode,
  slide: number,
  afirmacion: string,
  tono: TonoTarjeta,
  animada: boolean,
): boolean {
  const divs = raiz.querySelectorAll<HTMLElement>(`#slide-${slide} [data-campo] div`);

  // Se prueba cada campo de texto del slide hasta dar con la afirmación.
  for (const div of Array.from(divs)) {
    const texto = div.textContent ?? "";
    const posicion = localizarAfirmacion(texto, afirmacion);
    // Este campo no contiene la afirmación: se sigue con el siguiente.
    if (posicion === null) continue;

    const marca = document.createElement("mark");
    marca.className = `marca-revisor marca-${tono}${animada ? " marca-nueva" : ""}`;
    marca.textContent = texto.slice(posicion.inicio, posicion.fin);
    div.replaceChildren(texto.slice(0, posicion.inicio), marca, texto.slice(posicion.fin));
    return true;
  }
  return false;
}