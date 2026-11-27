/**
 * TiraMiniaturas.tsx — Fila con una miniatura por slide de la plantilla.
 * La del slide activo va resaltada; las que aún no tienen contenido quedan
 * deshabilitadas. Al hacer clic se ve ese slide tal como está ahora (onVerSlide), sin
 * mover la reproducción: el run sigue por detrás. El número de slides sale de la plantilla.
 * Un slide con solo campos calculados por código (el de fuentes y sello) también se habilita.
 */
import { useEffect, useMemo, useState } from "react";
import { esperarFuentes, parsearPlantilla } from "./cargarPlantilla.ts";
import type { IdiomaFase } from "./fase.ts";
import { slideTieneContenido } from "./slideTieneContenido.ts";
import { MiniaturaSlide } from "./MiniaturaSlide.tsx";
// NUEVO: campos de cada slide y regla de contenido calculado.
import { camposPorSlide, slideTieneCalculado } from "./slideManual.ts";
import type { CamposPorSlide } from "./slideManual.ts";
import type { Estado } from "../timeline/types.ts";

// Textos accesibles por idioma.
const TEXTOS: Record<IdiomaFase, { nav: string; ir: string }> = {
  es: { nav: "Slides del carrusel", ir: "Ir al slide" },
  "pt-BR": { nav: "Slides do carrossel", ir: "Ir para o slide" },
};

// Datos de la plantilla que usa la tira: cuántos slides tiene y qué campos lleva cada uno.
interface DatosPlantilla {
  readonly numeroSlides: number;
  readonly campos: CamposPorSlide;
}

interface PropsTira {
  readonly svg: string;
  // Estado que se está viendo (con el slide manual ya aplicado, si lo hay).
  readonly estado: Estado;
  readonly idioma: IdiomaFase;
  // La persona quiere ver este slide.
  readonly onVerSlide: (slide: number) => void;
}

export function TiraMiniaturas({ svg, estado, idioma, onVerSlide }: PropsTira) {
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

  // Cantidad de slides y campos de cada uno: se leen de la plantilla una sola vez por svg.
  const { numeroSlides, campos } = useMemo<DatosPlantilla>(() => {
    try {
      const raiz = parsearPlantilla(svg);
      return {
        numeroSlides: raiz.querySelectorAll("g.slide").length,
        campos: camposPorSlide(raiz),
      };
    } catch {
      // Plantilla inválida: sin miniaturas (el lienzo principal muestra el error).
      return { numeroSlides: 0, campos: {} };
    }
  }, [svg]);

  const textos = TEXTOS[idioma];

  return (
    <nav className="tira-miniaturas" aria-label={textos.nav}>
      {/* Un ciclo por slide: crea su miniatura. */}
      {Array.from({ length: numeroSlides }, (_, i) => {
        const slide = i + 1;
        // NUEVO: ¿el slide ya tiene texto calculado por código (atribución, licencia, sello)?
        const tieneCalculado = slideTieneCalculado(estado, campos[slide] ?? []);
        // Deshabilitada solo mientras no haya nada que mirar.
        const deshabilitada = !slideTieneContenido(estado, slide) && !tieneCalculado;
        return (
          <MiniaturaSlide
            key={slide}
            svg={svg}
            estado={estado}
            slide={slide}
            activa={estado.slideActivo === slide}
            deshabilitada={deshabilitada}
            etiqueta={`${textos.ir} ${slide}`}
            fuentesListas={fuentesListas}
            onSeleccionar={() => onVerSlide(slide)}
          />
        );
      })}
    </nav>
  );
}