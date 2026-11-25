/**
 * PanelAprobacion.tsx — Panel de la aprobación humana (HITL) en modo Servidor.
 * Aparece mientras el run espera la decisión: muestra el sello de la revisión, un cuadro de texto por campo
 * y los botones «Aprobar» / «Aprobar con cambios». Los eventos `editada`, `aprobada` y `run_finalizada` los
 * emite el servidor y llegan por el SSE: el panel solo envía la decisión y muestra los motivos si la rechaza.
 * Las ediciones no se vuelven a verificar contra la fuente, y el panel lo dice.
 */
import { useState } from "react";
import type { Estado } from "../timeline/types.ts";
import {
  camposEditables,
  camposModificados,
  claveCampo,
  cuerpoDecision,
  enviarAprobacion,
  esperaAprobacion,
  textoActual,
} from "./aprobacion.ts";
import type { Borradores } from "./aprobacion.ts";

export function PanelAprobacion({ estado, runId }: { estado: Estado; runId: string }) {
  const [borradores, setBorradores] = useState<Borradores>({});
  const [comentario, setComentario] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [motivos, setMotivos] = useState<readonly string[]>([]);

  // Tras decidir, el panel se reemplaza por un aviso con lo que quedó editado a mano.
  if (estado.decision !== null || estado.final !== null) {
    const n = estado.ediciones.length;
    if (n === 0) return null;
    return (
      <aside className="panel-aprobacion panel-aprobacion-cerrado" role="status">
        {n === 1 ? "1 campo editado a mano" : `${n} campos editados a mano`}: no se volvió a verificar contra la fuente.
      </aside>
    );
  }
  if (!esperaAprobacion(estado) || estado.revision === null) return null;

  const campos = camposEditables(estado);
  const cambios = camposModificados(estado, borradores).length;
  const sello = estado.revision.sello;

  async function decidir() {
    setEnviando(true);
    setMotivos([]);
    const r = await enviarAprobacion(runId, cuerpoDecision(estado, borradores, comentario));
    setEnviando(false);
    // Si salió bien no hay nada más que hacer: el SSE trae `aprobada` y el panel se reemplaza solo.
    if (!r.ok) setMotivos(r.motivos);
  }

  return (
    <aside className="panel-aprobacion" aria-label="Aprobación">
      <h2>Aprobación</h2>
      <p className="panel-aprobacion-sello">
        Sello: {sello.afirmaciones_respaldadas} de {sello.afirmaciones_totales} afirmaciones respaldadas
        {estado.revision.hallazgos_abiertos > 0 && ` · ${estado.revision.hallazgos_abiertos} hallazgo(s) abierto(s)`}
      </p>
      <p className="panel-aprobacion-aviso">
        Lo que edites aquí no se vuelve a verificar contra la fuente: el sello cubre solo lo que escribió el modelo.
      </p>

      {campos.map((c) => (
        <label key={claveCampo(c.slide, c.campo)} className="panel-aprobacion-campo">
          Slide {c.slide} · {c.campo}
          <textarea
            rows={c.texto.length > 80 ? 3 : 1}
            maxLength={400}
            value={textoActual(borradores, c)}
            disabled={enviando}
            onChange={(e) => {
              const valor = e.currentTarget.value;
              setBorradores((previos) => ({ ...previos, [claveCampo(c.slide, c.campo)]: valor }));
            }}
          />
        </label>
      ))}

      <label className="panel-aprobacion-campo">
        Comentario (opcional)
        <textarea
          rows={1}
          maxLength={400}
          value={comentario}
          disabled={enviando}
          onChange={(e) => setComentario(e.currentTarget.value)}
        />
      </label>

      {/* Barra fija al borde inferior: el botón y los errores del servidor se ven sin tener que bajar hasta los campos. */}
      <div className="panel-aprobacion-barra">
        {motivos.length > 0 && (
          <ul role="alert" className="panel-aprobacion-errores">
            {motivos.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        )}
        <div className="panel-aprobacion-botones">
          <span className="panel-aprobacion-estado">
            {sello.afirmaciones_respaldadas}/{sello.afirmaciones_totales} respaldadas
          </span>
          <button type="button" disabled={enviando} onClick={() => void decidir()}>
            {enviando ? "Enviando…" : cambios > 0 ? `Aprobar con ${cambios} cambio${cambios === 1 ? "" : "s"}` : "Aprobar"}
          </button>
        </div>
      </div>
    </aside>
  );
}
