/**
 * Lienzo.tsx — Muestra el SVG de la plantilla y lo pinta con la vista del reproductor.
 * gsap solo anima el <foreignObject> de cada campo (opacidad), nunca el texto interno,
 * para no pelear con el ajuste de tamaño.
 */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import gsap from "gsap";
import { esperarFuentes, parsearPlantilla } from "./cargarPlantilla.ts";
import { pintarLienzo } from "./pintarLienzo.ts";
import type { VistaReproductor } from "../timeline/reproductor.ts";

// Duración base del fade-in de un texto (s); se divide por la velocidad de reproducción.
const DURACION_FADE_S = 0.4;

interface PropsLienzo {
  // Estado y reproducción actuales.
  readonly vista: VistaReproductor;
  // Texto del template.svg ya con las rutas de fuentes corregidas.
  readonly svg: string;
}

export function Lienzo({ vista, svg }: PropsLienzo) {
  const contenedor = useRef<HTMLDivElement | null>(null);
  const [montado, setMontado] = useState(false);
  const [fuentesListas, setFuentesListas] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Últimos textos pintados por "slide:campo", para animar solo lo que cambió.
  const textosPrevios = useRef<Map<string, string>>(new Map());

  // Monta el SVG una vez por plantilla y espera las tipografías antes de medir.
  useEffect(() => {
    const cont = contenedor.current;
    if (!cont) return;
    let cancelado = false;

    try {
      const raiz = parsearPlantilla(svg);
      cont.replaceChildren(document.importNode(raiz, true));

      // El SVG se adapta al ancho del contenedor; el viewBox mantiene la proporción.
      const svgEl = cont.querySelector("svg");
      if (svgEl) {
        svgEl.removeAttribute("width");
        svgEl.removeAttribute("height");
        svgEl.style.width = "100%";
        svgEl.style.height = "auto";
        svgEl.style.display = "block";
      }
      setError(null);
      setMontado(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return;
    }

    // Cuando las fuentes terminan, se vuelve a pintar para medir con la tipografía real.
    void esperarFuentes().then(() => {
      if (!cancelado) setFuentesListas(true);
    });

    // Al desmontar se limpia el SVG y se cancelan las animaciones en curso.
    return () => {
      cancelado = true;
      gsap.killTweensOf(cont.querySelectorAll("foreignObject"));
      cont.replaceChildren();
      setMontado(false);
      setFuentesListas(false);
      textosPrevios.current = new Map();
    };
  }, [svg]);

  // Pinta en cada cambio de estado y anima los textos que acaban de cambiar.
  useLayoutEffect(() => {
    const cont = contenedor.current;
    if (!cont || !montado) return;

    pintarLienzo(cont, vista.estado);

    // Solo se anima al reproducir y si la persona no pidió reducir el movimiento.
    const reducirMovimiento =
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const animar = vista.reproduciendo && !reducirMovimiento;

    const actuales = new Map<string, string>();

    // Un ciclo por slide con textos dibujados.
    for (const [slideTxt, campos] of Object.entries(vista.estado.lienzo.textos)) {
      const slide = Number(slideTxt);

      // Un ciclo por campo del slide.
      for (const [campo, texto] of Object.entries(campos)) {
        const clave = `${slide}:${campo}`;
        actuales.set(clave, texto);

        // Texto sin cambios, o slide que no se ve: no hay nada que animar.
        if (textosPrevios.current.get(clave) === texto) continue;
        if (!animar || slide !== vista.estado.slideActivo) continue;

        const campoEl = cont.querySelector(`#slide-${slide} [data-campo="{{${campo}}}"]`);
        // Fade-in sobre el foreignObject, no sobre el texto interno.
        if (campoEl) {
          gsap.fromTo(
            campoEl,
            { opacity: 0 },
            {
              opacity: 1,
              duration: DURACION_FADE_S / vista.velocidad,
              ease: "power1.out",
              overwrite: "auto",
            },
          );
        }
      }
    }

    // Se reemplaza el mapa completo: al reiniciar, un texto que vuelve a aparecer anima otra vez.
    textosPrevios.current = actuales;
  }, [vista.estado, vista.reproduciendo, vista.velocidad, montado, fuentesListas]);

  // Error de carga o de parseo: mensaje visible en vez de un lienzo vacío.
  if (error) {
    return <p role="alert">No se pudo mostrar el lienzo: {error}</p>;
  }
  return <div ref={contenedor} className="lienzo" role="img" aria-label="Vista previa del carrusel" />;
}