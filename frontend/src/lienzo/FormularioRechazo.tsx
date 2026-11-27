/**
 * FormularioRechazo.tsx — Los datos de un rechazo. Solo el motivo es obligatorio; quién falló, en qué slide y qué
 * debía hacer son opcionales, y son lo que más sirve para que el agente aprenda del rechazo más adelante.
 */
import { motivoDemasiadoGeneral, RESPONSABLES } from "./aprobacion.ts";
import type { BorradorRechazo, Responsable } from "./aprobacion.ts";

const NOMBRES: Readonly<Record<Responsable, string>> = {
  redactor: "Redactor",
  revisor: "Revisor",
  director_arte: "Director de arte",
  estratega: "Estratega",
};

export function FormularioRechazo({
  valor,
  slides,
  deshabilitado,
  alCambiar,
}: {
  valor: BorradorRechazo;
  slides: readonly number[];
  deshabilitado: boolean;
  alCambiar: (valor: BorradorRechazo) => void;
}) {
  // Si el motivo es muy general y todavía no dijo qué esperaba, se le pide una pista (no bloquea).
  const pedirDetalle = motivoDemasiadoGeneral(valor.motivo) && valor.esperado.trim() === "";
  return (
    <>
      <p className="panel-aprobacion-aviso">
        El carrusel se cierra como rechazado. Tu motivo queda guardado en esta computadora.
      </p>
      <label className="panel-aprobacion-campo">
        ¿Por qué lo rechazás? (obligatorio)
        <textarea
          rows={3}
          maxLength={400}
          autoFocus
          value={valor.motivo}
          disabled={deshabilitado}
          onChange={(e) => alCambiar({ ...valor, motivo: e.currentTarget.value })}
        />
      </label>
      {pedirDetalle && (
        <p className="panel-aprobacion-pregunta" role="note">
          Ese motivo es muy general: el agente no puede aprender de él. ¿Qué frase o dato falló, y qué esperabas en su
          lugar? Completá «qué debería haber hecho» más abajo.
        </p>
      )}
      <label className="panel-aprobacion-campo">
        ¿Qué agente falló? (opcional)
        <select
          value={valor.responsable}
          disabled={deshabilitado}
          onChange={(e) => alCambiar({ ...valor, responsable: e.currentTarget.value as Responsable | "" })}
        >
          <option value="">No lo sé</option>
          {RESPONSABLES.map((r) => (
            <option key={r} value={r}>
              {NOMBRES[r]}
            </option>
          ))}
        </select>
      </label>
      <label className="panel-aprobacion-campo">
        ¿En qué slide? (opcional)
        <select
          value={valor.slide ?? ""}
          disabled={deshabilitado}
          onChange={(e) => alCambiar({ ...valor, slide: e.currentTarget.value === "" ? null : Number(e.currentTarget.value) })}
        >
          <option value="">Todo el carrusel</option>
          {slides.map((n) => (
            <option key={n} value={n}>
              Slide {n}
            </option>
          ))}
        </select>
      </label>
      <label className="panel-aprobacion-campo">
        ¿Qué debería haber hecho? (opcional)
        <textarea
          rows={2}
          maxLength={400}
          value={valor.esperado}
          disabled={deshabilitado}
          onChange={(e) => alCambiar({ ...valor, esperado: e.currentTarget.value })}
        />
      </label>
    </>
  );
}
