/**
 * RevisionSlide.tsx — Lo que se ve debajo de las miniaturas mientras la persona revisa un slide: cómo volver al
 * directo, los problemas que el revisor abrió ahí (abiertos y ya corregidos) y, cuando el run ya pidió la
 * aprobación, los demás motivos por los que el semáforo del servidor lo tiene en rojo.
 */
import { useEffect, useState } from "react";
import type { Estado } from "../timeline/types.ts";
import { motivosSinHallazgo, pedirInforme } from "./aprobacion.ts";
import type { Informe } from "./aprobacion.ts";
import { problemasDelSlide } from "./slideManual.ts";

export function RevisionSlide({ estado, slide, onVolver }: { estado: Estado; slide: number; onVolver: () => void }) {
  const { abiertos, corregidos } = problemasDelSlide(estado, slide);
  const [informe, setInforme] = useState<Informe | null>(null);
  // Antes de pedir la aprobación el semáforo está a medias: marcaría en rojo lo que aún no se revisó.
  const pedir = estado.revision !== null ? estado.runId : null;

  useEffect(() => {
    setInforme(null);
    if (pedir === null) return;
    let cancelado = false;
    // En la grabación local no hay servidor: queda en null y se muestra solo lo del revisor.
    void pedirInforme(pedir).then((i) => {
      if (!cancelado) setInforme(i);
    });
    return () => {
      cancelado = true;
    };
  }, [pedir, estado.ultimoSeq]);

  const fila = informe?.slides.find((s) => s.slide === slide);
  const otros = informe ? motivosSinHallazgo(informe, slide) : [];

  return (
    <section className="revision-slide" aria-label={`Revisión del slide ${slide}`}>
      <p className="revision-slide-cabecera">
        <strong>
          Estás revisando el slide {slide}
          {fila ? ` · semáforo: ${fila.color}` : ""}.
        </strong>
        <button type="button" onClick={onVolver}>
          Volver al directo
        </button>
      </p>
      {abiertos.length === 0 && otros.length === 0 && fila?.color !== "rojo" && (
        <p>Sin problemas abiertos en este slide. Eso no es una aprobación.</p>
      )}
      <ul>
        {abiertos.map((h) => (
          <li key={h.hallazgo_id} className="revision-problema">
            <strong>
              Problema abierto ({h.gravedad}): {h.evidencia}
            </strong>
            <span>{h.explicacion}</span>
          </li>
        ))}
        {otros.map((m) => (
          <li key={m} className="revision-problema">
            <span>{m}</span>
          </li>
        ))}
        {corregidos.map((h) => (
          <li key={h.hallazgo_id} className="revision-problema revision-corregido">
            <strong>Ya corregido: {h.evidencia}</strong>
            <span>{h.explicacion}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
