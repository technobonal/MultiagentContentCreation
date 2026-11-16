/**
 * TarjetaRevisorVista.tsx — Tarjeta flotante sobre el lienzo con lo que el revisor
 * (o el humano) acaba de hacer: veredicto, motivo y cita de la fuente.
 */
import type { TarjetaRevisor } from "./revisor.ts";

export function TarjetaRevisorVista({ tarjeta }: { tarjeta: TarjetaRevisor }) {
  return (
    <aside className={`tarjeta tarjeta-${tarjeta.tono}`} role="status">
      <p className="tarjeta-titulo">{tarjeta.titulo}</p>

      {/* Una línea por frase (afirmación, motivo, acción…). */}
      {tarjeta.lineas.map((linea, i) => (
        <p key={i}>{linea}</p>
      ))}

      {/* Cita de la fuente o evidencia, si la hay. */}
      {tarjeta.cita !== null && (
        <blockquote className="tarjeta-cita">
          <span className="tarjeta-cita-etiqueta">{tarjeta.cita.etiqueta}</span>
          {tarjeta.cita.texto}
        </blockquote>
      )}
    </aside>
  );
}