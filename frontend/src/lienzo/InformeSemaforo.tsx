/**
 * InformeSemaforo.tsx — El semáforo por slide que calcula el servidor (GET /api/runs/{id}/informe).
 * Solo lo muestra: quien decide si se puede aprobar es el servidor.
 */
import type { Informe } from "./aprobacion.ts";

export function InformeSemaforo({ informe }: { informe: Informe }) {
  return (
    <section className="semaforo" aria-label="Informe de revisión">
      <p className={`semaforo-resumen semaforo-${informe.visto_bueno ? "verde" : "rojo"}`}>
        {informe.visto_bueno ? "Con visto bueno: pasó los controles" : "Sin visto bueno"}
      </p>
      {informe.generales.map((m) => (
        <p key={m} className="semaforo-motivo">
          {m}
        </p>
      ))}
      <ul>
        {informe.slides.map((s) => (
          <li key={s.slide} className={`semaforo-slide semaforo-${s.color}`}>
            <strong>
              Slide {s.slide}: {s.color}
            </strong>
            {s.motivos.map((m) => (
              <span key={m} className="semaforo-motivo">
                {m}
              </span>
            ))}
            {s.avisos.map((m) => (
              <span key={m} className="semaforo-motivo semaforo-aviso">
                Aviso (no bloquea). {m}
              </span>
            ))}
          </li>
        ))}
      </ul>
      <p className="panel-aprobacion-aviso">Verde significa que pasó los controles, no que sea verdad: el revisor puede equivocarse.</p>
    </section>
  );
}
