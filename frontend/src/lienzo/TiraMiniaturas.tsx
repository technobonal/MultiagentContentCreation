/**
 * TiraMiniaturas.tsx — Fila con una miniatura por slide de la plantilla.
 * La del slide activo va resaltada; las que aún no tienen contenido quedan
 * deshabilitadas. Al hacer clic se salta (irA) al primer punto donde ese slide
 * ya tiene contenido. El número de slides sale de la propia plantilla.
 */
import { useEffect, useMemo, useState } from "react";
import { esperarFuentes, parsearPlantilla } from "./cargarPlantilla.ts";
import type { IdiomaFase } from "./fase.ts";
import { indiceDeSalto, slideTieneContenido } from "./indiceDeSalto.ts";
import { MiniaturaSlide } from "./MiniaturaSlide.tsx";
import type { Estado, Evento } from "../timeline/types.ts";

// Textos accesibles por idioma.
const TEXTOS: Record<IdiomaFase, { nav: string; ir: string }> = {
  es: { nav: "Slides del carrusel", ir: "Ir al slide" },
  "pt-BR": { nav: "Slides do carrossel", ir: "Ir para o slide" },
};

interface PropsTira {
  readonly svg: string;
  readonly estado: Estado;
  // Eventos de la grabación (para calcular a dónde saltar).
  readonly eventos: readonly Evento[];
  readonly idioma: IdiomaFase;
  // Salta a un punto con `indice` eventos aplicados.
  readonly onIrA: (indice: number) => void;
}

export function TiraMiniaturas({ svg, estado, eventos, idioma, onIrA }: PropsTira) {
  const [fuentesListas, setFuentesListas] = useState(false);

  // Espera las tipografías una vez: sin ellas las miniaturas se medirían con la fuente de respaldo.
  useEffect(() => {
    let cancelado = false;
    void esperarFuentes().then(() => {
      // Si el componente se desmontó mientras tanto, se descarta.
      if (!cancelado) setFuentesListas(true);
    });
    return () => {
      cancelado = true;
    };
  }, []);

  // Cantidad de slides: cuenta los <g class="slide"> de la plantilla.
  const numeroSlides = useMemo(() => {
    try {
      return parsearPlantilla(svg).querySelectorAll("g.slide").length;
    } catch {
      // Plantilla inválida: sin miniaturas (el lienzo principal muestra el error).
      return 0;
    }
  }, [svg]);

  // Punto de salto de cada slide (índice 0 = slide 1); solo cambia con la grabación.
  const saltos = useMemo(
    () => Array.from({ length: numeroSlides }, (_, i) => indiceDeSalto(eventos, i + 1)),
    [eventos, numeroSlides],
  );

  const textos = TEXTOS[idioma];

  return (
    <nav className="tira-miniaturas" aria-label={textos.nav}>
      {/* Un ciclo por slide: crea su miniatura. */}
      {saltos.map((salto, i) => {
        const slide = i + 1;
        return (
          <MiniaturaSlide
            key={slide}
            svg={svg}
            estado={estado}
            slide={slide}
            activa={estado.slideActivo === slide}
            // Deshabilitada si aún no hay contenido o si ningún evento le da contenido.
            deshabilitada={salto === null || !slideTieneContenido(estado, slide)}
            etiqueta={`${textos.ir} ${slide}`}
            fuentesListas={fuentesListas}
            onSeleccionar={() => {
              // Solo se salta si existe un punto de salto para este slide.
              if (salto !== null) onIrA(salto);
            }}
          />
        );
      })}
    </nav>
  );
}