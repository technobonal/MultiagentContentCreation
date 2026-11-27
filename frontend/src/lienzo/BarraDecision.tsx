/**
 * BarraDecision.tsx — La barra fija de abajo donde se decide el carrusel entero (principio «decidí abajo»).
 * Solo maqueta: a la izquierda un semáforo compacto (un punto por slide, verde/rojo) que al tocarlo salta
 * a ese slide arriba, en el medio el recuento de afirmaciones respaldadas, y a la derecha los botones que
 * le pasa el panel como children (él decide la jerarquía). No conoce la lógica de la decisión.
 */
import type { ReactNode } from "react";

interface PropsBarra {
  // Un punto por slide, en orden; el color sale del semáforo del servidor.
  readonly slides: readonly { readonly slide: number; readonly color: "verde" | "rojo" }[];
  readonly respaldadas: number;
  readonly totales: number;
  // Slide que se está revisando arriba (se resalta su punto); null si se mira el directo.
  readonly slideActivo?: number | null;
  // La persona tocó un punto: quiere ver ese slide arriba.
  readonly onIrSlide: (slide: number) => void;
  // Botones de decisión, ya con su jerarquía puesta por el panel.
  readonly children: ReactNode;
}

export function BarraDecision({ slides, respaldadas, totales, slideActivo, onIrSlide, children }: PropsBarra) {
  return (
    <div className="barra-decision">
      {slides.length > 0 && (
        <ul className="barra-semaforo" aria-label="Semáforo por slide">
          {slides.map((s) => (
            <li key={s.slide}>
              <button
                type="button"
                className={`barra-punto barra-punto-${s.color}${slideActivo === s.slide ? " barra-punto-activo" : ""}`}
                // El título sale como tooltip del navegador al pasar el mouse; el aria-label lo lee el lector.
                title={`Slide ${s.slide}: ${s.color === "verde" ? "con visto bueno" : "en rojo"}`}
                aria-label={`Ir al slide ${s.slide}, ${s.color === "verde" ? "con visto bueno" : "en rojo"}`}
                aria-current={slideActivo === s.slide ? "true" : undefined}
                onClick={() => onIrSlide(s.slide)}
              >
                <span className="barra-punto-numero" aria-hidden="true">
                  {s.slide}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <span className="barra-recuento">
        {respaldadas}/{totales} respaldadas
      </span>
      <div className="barra-botones">{children}</div>
    </div>
  );
}
