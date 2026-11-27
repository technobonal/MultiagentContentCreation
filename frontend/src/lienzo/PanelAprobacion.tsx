/**
 * PanelAprobacion.tsx — Panel de la aprobación humana (HITL) en modo Servidor.
 * Aparece mientras el run espera la decisión: muestra el sello de la revisión, un cuadro de texto por campo
 * y los botones «Aprobar» / «Aprobar con cambios» y «Rechazar» (que pide el motivo). Los eventos `editada`,
 * `aprobada`, `rechazada` y `run_finalizada` los
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
  cuerpoRechazo,
  enviarAprobacion,
  esperaAprobacion,
  RECHAZO_VACIO,
  textoActual,
} from "./aprobacion.ts";
import type { Borradores, CuerpoDecision, CuerpoRechazo } from "./aprobacion.ts";
import { FormularioRechazo } from "./FormularioRechazo.tsx";

export function PanelAprobacion({ estado, runId }: { estado: Estado; runId: string }) {
  const [borradores, setBorradores] = useState<Borradores>({});
  const [comentario, setComentario] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [motivos, setMotivos] = useState<readonly string[]>([]);
  // null: no se está rechazando; si no, lo que la persona lleva escrito.
  const [rechazo, setRechazo] = useState<typeof RECHAZO_VACIO | null>(null);

  // Tras decidir, el panel se reemplaza por un aviso con lo que quedó editado a mano.
  if (estado.decision !== null || estado.final !== null) {
    const rechazado = estado.decision?.rechazo;
    if (rechazado !== undefined) {
      return (
        <aside className="panel-aprobacion panel-aprobacion-cerrado" role="status">
          Carrusel rechazado{rechazado.slide === undefined ? "" : ` (slide ${rechazado.slide})`}: {rechazado.motivo}
        </aside>
      );
    }
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

  async function decidir(cuerpo: CuerpoDecision | CuerpoRechazo) {
    setEnviando(true);
    setMotivos([]);
    const r = await enviarAprobacion(runId, cuerpo);
    setEnviando(false);
    // Si salió bien no hay nada más que hacer: el SSE trae `aprobada` y el panel se reemplaza solo.
    if (!r.ok) setMotivos(r.motivos);
  }

  return (
    <aside className="panel-aprobacion" aria-label="Aprobación">
      <h2>{rechazo === null ? "Aprobación" : "Rechazar el carrusel"}</h2>
      <p className="panel-aprobacion-sello">
        Sello: {sello.afirmaciones_respaldadas} de {sello.afirmaciones_totales} afirmaciones respaldadas
        {estado.revision.hallazgos_abiertos > 0 && ` · ${estado.revision.hallazgos_abiertos} hallazgo(s) abierto(s)`}
      </p>
      {rechazo !== null && (
        <FormularioRechazo
          valor={rechazo}
          slides={[...new Set(campos.map((c) => c.slide))]}
          deshabilitado={enviando}
          alCambiar={setRechazo}
        />
      )}

      {rechazo === null && (
        <p className="panel-aprobacion-aviso">
          Lo que edites aquí no se vuelve a verificar contra la fuente: el sello cubre solo lo que escribió el modelo.
        </p>
      )}

      {rechazo === null && campos.map((c) => (
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

      {rechazo === null && (
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
      )}

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
          {rechazo === null ? (
            <>
              <button
                type="button"
                className="boton-rechazar"
                disabled={enviando}
                onClick={() => {
                  setMotivos([]);
                  setRechazo(RECHAZO_VACIO);
                }}
              >
                Rechazar
              </button>
              <button type="button" disabled={enviando} onClick={() => void decidir(cuerpoDecision(estado, borradores, comentario))}>
                {enviando ? "Enviando…" : cambios > 0 ? `Aprobar con ${cambios} cambio${cambios === 1 ? "" : "s"}` : "Aprobar"}
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                disabled={enviando}
                onClick={() => {
                  setMotivos([]);
                  setRechazo(null);
                }}
              >
                Volver
              </button>
              <button
                type="button"
                className="boton-rechazar"
                disabled={enviando || rechazo.motivo.trim() === ""}
                onClick={() => void decidir(cuerpoRechazo(rechazo))}
              >
                {enviando ? "Enviando…" : "Confirmar rechazo"}
              </button>
            </>
          )}
        </div>
      </div>
    </aside>
  );
}
