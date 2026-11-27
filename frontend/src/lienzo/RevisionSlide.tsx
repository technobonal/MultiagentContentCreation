/**
 * RevisionSlide.tsx — Lo que se ve debajo de las miniaturas mientras la persona revisa un slide: cómo volver al
 * directo, los problemas que el revisor abrió ahí (abiertos y ya corregidos) y, cuando el run ya pidió la
 * aprobación, los demás motivos por los que el semáforo del servidor lo tiene en rojo.
 */
import { useEffect, useState } from "react";
import type { Estado } from "../timeline/types.ts";
import { camposEditables, claveCampo, esperaAprobacion, motivosSinHallazgo, pedirInforme, textoActual } from "./aprobacion.ts";
import type { Borradores, Informe } from "./aprobacion.ts";
import { cambiosDelSlide, cuerpoEdicion, pedirReverificacion } from "./reverificar.ts";
import { problemasDelSlide } from "./slideManual.ts";

export function RevisionSlide({
  estado,
  slide,
  onVolver,
  runId,
}: {
  estado: Estado;
  slide: number;
  onVolver: () => void;
  // Solo en modo Servidor: con un runId se puede volver a verificar el slide (A5).
  runId?: string;
}) {
  const { abiertos, corregidos } = problemasDelSlide(estado, slide);
  const [informe, setInforme] = useState<Informe | null>(null);
  const [borradores, setBorradores] = useState<Borradores>({});
  const [reverificando, setReverificando] = useState(false);
  const [motivos, setMotivos] = useState<readonly string[]>([]);
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
  // Alertas del asesor para este slide (si pidió una segunda opinión).
  const alertas = (estado.asesor?.alertas ?? []).filter((a) => a.slide === slide);

  // Re-verificación (A5): solo con servidor y mientras el run espera la decisión.
  const puedeReverificar = runId !== undefined && esperaAprobacion(estado);
  const campos = camposEditables(estado).filter((c) => c.slide === slide);
  const cambios = cambiosDelSlide(estado, borradores, slide);

  async function reverificar(cuerpo: Parameters<typeof pedirReverificacion>[1]) {
    if (runId === undefined) return;
    setReverificando(true);
    setMotivos([]);
    const r = await pedirReverificacion(runId, cuerpo);
    setReverificando(false);
    // Si salió bien, las verificaciones nuevas llegan por el SSE y el informe se recarga solo.
    if (r.ok) setBorradores({});
    else setMotivos(r.motivos);
  }

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
      {abiertos.length === 0 && otros.length === 0 && alertas.length === 0 && fila?.color !== "rojo" && (
        <p>Sin problemas abiertos en este slide. Eso no es una aprobación.</p>
      )}
      <ul>
        {alertas.map((a, i) => (
          <li key={`asesor-${i}`} className="revision-problema revision-asesor">
            <strong>El asesor marcó: «{a.frase}»</strong>
            <span>{a.explicacion}</span>
            <span className="revision-asesor-sugerencia">Sugerencia: {a.sugerencia}</span>
          </li>
        ))}
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

      {puedeReverificar && (
        <div className="revision-reverificar">
          {campos.map((c) => (
            <label key={claveCampo(c.slide, c.campo)} className="panel-aprobacion-campo">
              {c.campo}
              <textarea
                rows={c.texto.length > 80 ? 3 : 1}
                maxLength={400}
                value={textoActual(borradores, c)}
                disabled={reverificando}
                onChange={(e) => {
                  const valor = e.currentTarget.value;
                  setBorradores((previos) => ({ ...previos, [claveCampo(c.slide, c.campo)]: valor }));
                }}
              />
            </label>
          ))}
          {motivos.length > 0 && (
            <ul role="alert" className="panel-aprobacion-errores">
              {motivos.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          )}
          <div className="revision-reverificar-botones">
            <button
              type="button"
              disabled={reverificando || cambios === 0}
              onClick={() => void reverificar(cuerpoEdicion(estado, borradores, slide))}
            >
              {reverificando ? "Verificando…" : "Verificar mi edición"}
            </button>
            <button
              type="button"
              disabled={reverificando}
              onClick={() => void reverificar({ slide, modo: "agente" })}
            >
              Corregir con el agente
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
