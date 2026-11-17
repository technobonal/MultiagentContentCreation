/**
 * MiniaturaSlide.tsx — Una miniatura clicable de un slide.
 * Clona la plantilla SVG y la pinta con el estado actual, forzando que el slide
 * activo del clon sea el de esta miniatura. Solo se repinta cuando cambia algo
 * que afecta a ese slide (los objetos del reductor comparten estructura, así que
 * basta comparar referencias). Nunca se oculta con display:none: el medidor de
 * texto necesita elementos renderizados para medir bien.
 */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { parsearPlantilla } from "./cargarPlantilla.ts";
import { pintarLienzo } from "./pintarLienzo.ts";
import type { Estado } from "../timeline/types.ts";

interface PropsMiniatura {
  // Texto del template.svg (con las rutas de fuentes ya corregidas).
  readonly svg: string;
  // Estado actual del reproductor.
  readonly estado: Estado;
  // Número del slide que muestra esta miniatura (1..N).
  readonly slide: number;
  // true si es el slide que está activo en el lienzo principal.
  readonly activa: boolean;
  // true si el slide aún no tiene contenido o no hay a dónde saltar.
  readonly deshabilitada: boolean;
  // Texto accesible del botón.
  readonly etiqueta: string;
  // true cuando las tipografías ya cargaron (antes, el texto se mediría mal).
  readonly fuentesListas: boolean;
  // Se llama al hacer clic.
  readonly onSeleccionar: () => void;
}

export function MiniaturaSlide({
  svg,
  estado,
  slide,
  activa,
  deshabilitada,
  etiqueta,
  fuentesListas,
  onSeleccionar,
}: PropsMiniatura) {
  const contenedor = useRef<HTMLSpanElement | null>(null);
  const [montado, setMontado] = useState(false);

  // Monta un clon propio de la plantilla (una vez por plantilla).
  useEffect(() => {
    const cont = contenedor.current;
    if (!cont) return;

    try {
      const clon = document.importNode(parsearPlantilla(svg), true);
      // El SVG se adapta al ancho de la miniatura; el viewBox mantiene la proporción.
      clon.removeAttribute("width");
      clon.removeAttribute("height");
      clon.style.width = "100%";
      clon.style.height = "auto";
      clon.style.display = "block";
      cont.replaceChildren(clon);
      setMontado(true);
    } catch {
      // Si la plantilla no es válida, el lienzo principal ya muestra el error.
      setMontado(false);
    }

    // Al desmontar se limpia el clon.
    return () => {
      cont.replaceChildren();
      setMontado(false);
    };
  }, [svg]);

  // Referencias de lo que afecta a este slide: si no cambian, no se repinta.
  const textos = estado.lienzo.textos[slide];
  const fondo = estado.lienzo.fondos[slide];
  const borradores = estado.propuestas[slide];

  // Pinta el clon con el slide forzado como activo.
  useLayoutEffect(() => {
    const cont = contenedor.current;
    // Sin clon montado o sin fuentes cargadas no se pinta todavía.
    if (!cont || !montado || !fuentesListas) return;
    pintarLienzo(cont, { ...estado, slideActivo: slide }, undefined, { borradores: true });
    // Se repinta solo con las referencias de arriba y las fuentes de los campos calculados
    // (sello, atribución, licencia). Si algún campo calculado no se refresca, añade aquí su origen.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    montado,
    fuentesListas,
    slide,
    textos,
    fondo,
    borradores,
    estado.run,
    estado.fuente,
    estado.brief,
    estado.plantilla,
    estado.ledger,
    estado.revision,
    estado.final,
  ]);

  return (
    <button
      type="button"
      className={`miniatura${activa ? " miniatura-activa" : ""}`}
      aria-label={etiqueta}
      aria-current={activa ? "true" : undefined}
      disabled={deshabilitada}
      onClick={onSeleccionar}
    >
      <span ref={contenedor} className="miniatura-svg" aria-hidden="true" />
      <span className="miniatura-numero">{slide}</span>
    </button>
  );
}