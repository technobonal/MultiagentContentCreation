/**
 * TiraMiniaturas.tsx — Fila con una miniatura por slide de la plantilla.
 * La del slide activo va resaltada; las que aún no tienen contenido quedan
 * deshabilitadas. Al hacer clic se salta (irA) al primer punto donde ese slide
 * ya tiene contenido. El número de slides sale de la propia plantilla.
 * CAMBIO: un slide sin ningún evento pero con campos calculados por código (el de
 * fuentes y sello) también se habilita; como no hay punto de salto, al hacer clic
 * se ve a mano (onVerSlide) sin mover el tiempo de la reproducción.
 */
import { useEffect, useMemo, useState } from "react";
import { esperarFuentes, parsearPlantilla } from "./cargarPlantilla.ts";
import type { IdiomaFase } from "./fase.ts";
import { indiceDeSalto, slideTieneContenido } from "./indiceDeSalto.ts";
import { MiniaturaSlide } from "./MiniaturaSlide.tsx";
// NUEVO: campos de cada slide y regla de contenido calculado.
import { camposPorSlide, slideTieneCalculado } from "./slideManual.ts";
import type { CamposPorSlide } from "./slideManual.ts";
import type { Estado, Evento } from "../timeline/types.ts";

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
  // Eventos de la grabación (para calcular a dónde saltar).
  readonly eventos: readonly Evento[];
  readonly idioma: IdiomaFase;
  // Salta a un punto con `indice` eventos aplicados.
  readonly onIrA: (indice: number) => void;
  // NUEVO: muestra a mano un slide sin punto de salto (por ejemplo el de fuentes y sello).
  readonly onVerSlide: (slide: number) => void;
}

export function TiraMiniaturas({ svg, estado, eventos, idioma, onIrA, onVerSlide }: PropsTira) {
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
        // NUEVO: ¿el slide ya tiene texto calculado por código (atribución, licencia, sello)?
        const tieneCalculado = slideTieneCalculado(estado, campos[slide] ?? []);
        // Deshabilitada si aún no hay contenido o ningún evento le da contenido,
        // salvo que tenga contenido calculado que se pueda ver a mano.
        const deshabilitada =
          (salto === null || !slideTieneContenido(estado, slide)) && !tieneCalculado;
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
            onSeleccionar={() => {
              // Con punto de salto se mueve el tiempo, como siempre.
              if (salto !== null) {
                onIrA(salto);
                return;
              }
              // Sin punto de salto (solo contenido calculado): se ve a mano, sin mover el tiempo.
              onVerSlide(slide);
            }}
          />
        );
      })}
    </nav>
  );
}