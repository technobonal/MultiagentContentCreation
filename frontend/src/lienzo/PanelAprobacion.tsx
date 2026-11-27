/**
 * PanelAprobacion.tsx — Panel de la aprobación humana (HITL) en modo Servidor.
 * Aparece mientras el run espera la decisión: muestra el sello de la revisión, un cuadro de texto por campo
 * y los botones «Aprobar» / «Aprobar con cambios» y «Rechazar» (que pide el motivo). Los eventos `editada`,
 * `aprobada`, `rechazada` y `run_finalizada` los
 * emite el servidor y llegan por el SSE: el panel solo envía la decisión y muestra los motivos si la rechaza.
 * Arriba va el semáforo del servidor; en rojo (o si hay ediciones, que no se re-verifican) solo se puede aprobar
 * escribiendo una excepción, y el run queda marcado «sin visto bueno».
 */
import { useEffect, useState } from "react";
import type { Estado } from "../timeline/types.ts";
import {
  camposEditables,
  cuerpoDecision,
  cuerpoRechazo,
  enviarAprobacion,
  esperaAprobacion,
  necesitaExcepcion,
  pedirConsejo,
  pedirInforme,
  RECHAZO_VACIO,
} from "./aprobacion.ts";
import type { CuerpoDecision, CuerpoRechazo, Informe } from "./aprobacion.ts";
import { InformeSemaforo } from "./InformeSemaforo.tsx";
import { FormularioRechazo } from "./FormularioRechazo.tsx";

export function PanelAprobacion({ estado, runId }: { estado: Estado; runId: string }) {
  const [comentario, setComentario] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [motivos, setMotivos] = useState<readonly string[]>([]);
  // null: no se está rechazando; si no, lo que la persona lleva escrito.
  const [rechazo, setRechazo] = useState<typeof RECHAZO_VACIO | null>(null);

  // undefined: cargando; null: no se pudo obtener.
  const [informe, setInforme] = useState<Informe | null | undefined>(undefined);
  const [excepcion, setExcepcion] = useState("");
  const [intento, setIntento] = useState(0);
  // Asesor: null = sin pedir; "confirmando" = mostrando el aviso; "consultando" = esperando a Cloudflare.
  const [consejo, setConsejo] = useState<null | "confirmando" | "consultando">(null);
  const esperando = esperaAprobacion(estado);

  useEffect(() => {
    if (!esperando) return;
    let cancelado = false;
    setInforme(undefined);
    void pedirInforme(runId).then((i) => {
      if (!cancelado) setInforme(i);
    });
    return () => {
      cancelado = true;
    };
  }, [esperando, runId, intento]);

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
    const sinAval = estado.decision?.excepcion;
    if (sinAval !== undefined) {
      return (
        <aside className="panel-aprobacion panel-aprobacion-cerrado" role="status">
          Aprobado por una persona, sin visto bueno: {sinAval.motivo}
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

  // Solo para la lista de slides del formulario de rechazo (editar un texto ya no se hace aquí, sino en la revisión).
  const campos = camposEditables(estado);
  const sello = estado.revision.sello;
  // Sin informe no se sabe si hay visto bueno: no se ofrece aprobar. Sin ediciones aquí, solo el rojo pide excepción.
  const enRojo = informe ? necesitaExcepcion(informe, 0) : false;

  async function decidir(cuerpo: CuerpoDecision | CuerpoRechazo) {
    setEnviando(true);
    setMotivos([]);
    const r = await enviarAprobacion(runId, cuerpo);
    setEnviando(false);
    // Si salió bien no hay nada más que hacer: el SSE trae `aprobada` y el panel se reemplaza solo.
    if (!r.ok) setMotivos(r.motivos);
  }

  async function consultarAsesor() {
    setConsejo("consultando");
    setMotivos([]);
    const r = await pedirConsejo(runId);
    setConsejo(null);
    // El servidor devuelve el semáforo ya actualizado; las alertas llegan además por el SSE.
    if (r.ok) setInforme(r.informe);
    else setMotivos(r.motivos);
  }

  // Resumen de la última asesoría: cuántas alertas y, si no hubo, el recordatorio de que eso no aprueba nada.
  const asesor = estado.asesor;
  const trabajando = enviando || consejo === "consultando";

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

      {informe === undefined && <p className="panel-aprobacion-aviso">Cargando el informe de revisión…</p>}
      {informe === null && (
        <p className="panel-aprobacion-aviso" role="alert">
          No se pudo cargar el informe: sin él no se puede aprobar.{" "}
          <button type="button" onClick={() => setIntento((n) => n + 1)}>
            Reintentar
          </button>
        </p>
      )}
      {informe && <InformeSemaforo informe={informe} />}

      {rechazo === null && (
        <div className="panel-asesor">
          {asesor && (
            <p className={`panel-asesor-resumen ${asesor.alertas.length > 0 ? "panel-asesor-con-alertas" : ""}`}>
              {asesor.alertas.length === 0
                ? `El asesor revisó ${asesor.frases_revisadas} frase(s) y no marcó ninguna. Eso no es una aprobación.`
                : `El asesor marcó ${asesor.alertas.length} frase(s): mirá cada slide en rojo para ver su consejo.`}
            </p>
          )}
          {consejo === "confirmando" ? (
            <div className="panel-asesor-confirmar" role="alertdialog" aria-label="Confirmar consulta al asesor">
              <p>Esto envía los textos y los fragmentos de la fuente a Cloudflare, y tarda cerca de un minuto. ¿Seguir?</p>
              <div className="panel-asesor-botones">
                <button type="button" disabled={trabajando} onClick={() => setConsejo(null)}>
                  Cancelar
                </button>
                <button type="button" disabled={trabajando} onClick={() => void consultarAsesor()}>
                  Enviar al asesor
                </button>
              </div>
            </div>
          ) : (
            <button type="button" className="boton-asesor" disabled={trabajando} onClick={() => setConsejo("confirmando")}>
              {consejo === "consultando" ? "El asesor está revisando…" : asesor ? "Pedir consejo otra vez" : "Pedir consejo"}
            </button>
          )}
        </div>
      )}

      {rechazo === null && enRojo && (
        <label className="panel-aprobacion-campo semaforo-excepcion">
          Para aprobar igual, escribí por qué (quedará como «aprobada sin visto bueno»)
          <textarea
            rows={2}
            maxLength={400}
            value={excepcion}
            disabled={enviando}
            onChange={(e) => setExcepcion(e.currentTarget.value)}
          />
        </label>
      )}

      {rechazo === null && (
        <p className="panel-aprobacion-aviso">
          Para cambiar un texto, tocá su slide arriba y usá «Verificar mi edición»: así se vuelve a verificar contra la fuente.
        </p>
      )}

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
                disabled={trabajando}
                onClick={() => {
                  setMotivos([]);
                  setRechazo(RECHAZO_VACIO);
                }}
              >
                Rechazar
              </button>
              <button
                type="button"
                disabled={trabajando || !informe || (enRojo && excepcion.trim() === "")}
                onClick={() => void decidir(cuerpoDecision(estado, {}, comentario, enRojo ? excepcion : ""))}
              >
                {enviando
                  ? "Enviando…"
                  : enRojo
                    ? "Aprobar sin visto bueno"
                    : "Aprobar"}
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
