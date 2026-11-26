/**
 * App.tsx — Pantalla principal: elige la fuente de eventos (grabación local o servidor SSE),
 * carga la plantilla y muestra la mesa de agentes, el lienzo, las miniaturas y los controles.
 * Lienzo no cambia entre fuentes: ambas cumplen la interfaz Reproductor.
 * En modo Servidor los botones 1x/2x/3x repiten el run guardado animado (el backend espacia los eventos
 * con ?ritmo=N); un run en curso sigue a su ritmo real.
 * CAMBIO: el slide que se mira puede elegirse a mano (miniatura sin eventos, como el de
 * fuentes y sello); la elección se suelta sola cuando llega un evento nuevo o se salta en el tiempo.
 * 9B-3: en modo Servidor, si la conexión termina en error se avisa al lienzo (`runFallido`)
 * para que el avatar vuelva a reposo con la burbuja de fallo.
 */
import { useEffect, useMemo, useState } from "react";
import { cargarGrabacion, listarGrabaciones } from "./lib/grabacion.ts";
import { idiomaDeGuia, leerEleccion } from "./lienzo/fase.ts";
import type { EleccionIdioma, IdiomaFase } from "./lienzo/fase.ts";
import { Lienzo } from "./lienzo/Lienzo.tsx";
import { MesaAgentes } from "./lienzo/MesaAgentes.tsx";
import { AvisoEspera } from "./lienzo/AvisoEspera.tsx";
import { PanelAprobacion } from "./lienzo/PanelAprobacion.tsx";
// NUEVO: reglas del slide elegido a mano.
import { aplicarSlideManual, slideManualVigente } from "./lienzo/slideManual.ts";
import type { SeleccionManual } from "./lienzo/slideManual.ts";
import { TiraMiniaturas } from "./lienzo/TiraMiniaturas.tsx";
// NUEVO: estado de la conexión SSE.
import { useEnVivo } from "./lienzo/useEnVivo.ts";
import { usePlantilla } from "./lienzo/usePlantilla.ts";
import { useReproductor } from "./lienzo/useReproductor.ts";
// NUEVO: fuente de eventos por SSE (misma interfaz que Reproductor).
import { crearFuenteEnVivo } from "./timeline/fuenteEnVivo.ts";
import type { EstadoConexion, FuenteEnVivo } from "./timeline/fuenteEnVivo.ts";
// Las velocidades salen del reproductor (única fuente de verdad); no hay lista local.
import { VELOCIDADES, crearReproductor } from "./timeline/reproductor.ts";
import type { Reproductor, VistaReproductor } from "./timeline/reproductor.ts";
import type { Evento } from "./timeline/types.ts";

// De dónde vienen los eventos.
type ModoFuente = "grabacion" | "servidor";

// Run que se propone por defecto en modo Servidor (la grabación b5 servida por el backend).
const RUN_POR_DEFECTO = "run_b5_cifra_inventada";

// Texto que se muestra para cada estado de la conexión.
const ETIQUETA_CONEXION: Record<EstadoConexion, string> = {
  conectando: "Conectando…",
  abierta: "Conectada",
  reconectando: "Reconectando…",
  cerrada: "Finalizada",
  error: "Error",
};

// Convierte cualquier error en un texto legible.
function mensaje(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

// Mesa de agentes, lienzo, miniaturas y controles de un reproductor ya creado.
function Pantalla({
  reproductor,
  idiomaGuia,
  eventos,
  runFallido = false,
}: {
  reproductor: Reproductor;
  idiomaGuia: IdiomaFase;
  // Eventos de la secuencia (la tira calcula a dónde saltar con ellos).
  eventos: readonly Evento[];
  // NUEVO (9B-3): el canal falló (solo modo Servidor; false por defecto).
  runFallido?: boolean;
}) {
  const vista = useReproductor(reproductor);
  // La plantilla la decide el run (evento plantilla_elegida); mientras no llega, la de por defecto.
  const { svg, error: errorSvg } = usePlantilla(
    vista.estado.plantilla?.plantilla_id,
    vista.estado.plantilla?.variante?.reemplazos,
  );

  // "auto" = idioma de la guía; si el usuario elige otro, manda su elección.
  // Esta pantalla se remonta al cambiar de fuente (key), así que vuelve a "auto".
  const [eleccion, setEleccion] = useState<EleccionIdioma>("auto");
  const idioma: IdiomaFase = eleccion === "auto" ? idiomaGuia : eleccion;

  // NUEVO: slide elegido a mano (con el último seq del reductor en ese momento).
  const [manual, setManual] = useState<SeleccionManual | null>(null);
  // Sigue vigente solo mientras no llegue un evento nuevo ni se salte a otro punto.
  const slideManual = slideManualVigente(manual, vista.estado.ultimoSeq);
  // Estado que se muestra: el del reductor con el slide manual aplicado (misma referencia si no hay).
  const estadoVista = useMemo(
    () => aplicarSlideManual(vista.estado, slideManual),
    [vista.estado, slideManual],
  );
  // Vista para el lienzo: igual que la del reproductor pero con el estado que se muestra.
  const vistaLienzo = useMemo<VistaReproductor>(
    () => ({ ...vista, estado: estadoVista }),
    [vista, estadoVista],
  );
  // Suelta la elección manual; se llama antes de cualquier acción que mueva la reproducción.
  const soltarManual = () => setManual(null);

  // NUEVO (9B-3): el aviso de fallo solo se muestra cuando la reproducción ya alcanzó el último
  // evento recibido (si no, el avatar diría "interrumpida" sobre un evento viejo).
  const fallidoVisible = runFallido && vista.aplicados >= vista.total;

  return (
    <div className="pantalla">
      {/* Selector del idioma de las etiquetas (letrero, agentes y tarjeta del revisor). */}
      <div className="idioma-fila">
        <select
          className="idioma-select"
          aria-label="Idioma de las etiquetas"
          value={eleccion}
          onChange={(e) => setEleccion(leerEleccion(e.currentTarget.value))}
        >
          <option value="auto">Guía (auto)</option>
          <option value="es">Español</option>
          <option value="pt-BR">Português</option>
        </select>
      </div>

      <MesaAgentes estado={vista.estado} idioma={idioma} />

      {errorSvg && <p role="alert">No se pudo cargar la plantilla: {errorSvg}</p>}
      {!svg && !errorSvg && <p>Cargando plantilla…</p>}
      {svg && !errorSvg && <Lienzo vista={vistaLienzo} svg={svg} idioma={idioma} runFallido={fallidoVisible} />}

      {/* Miniaturas; al hacer clic se salta al punto donde ese slide ya tiene contenido,
          o, si ningún evento lo toca (fuentes y sello), se ve a mano. */}
      {svg && !errorSvg && (
        <TiraMiniaturas
          svg={svg}
          estado={estadoVista}
          eventos={eventos}
          idioma={idioma}
          onIrA={(indice) => {
            soltarManual();
            reproductor.irA(indice);
          }}
          onVerSlide={(slide) => setManual({ slide, seq: vista.estado.ultimoSeq })}
        />
      )}

      <div className="controles">
        <div className="fila">
          {/* Alterna entre reproducir y pausar según el estado actual. */}
          <button
            type="button"
            onClick={() => {
              soltarManual();
              // Reproduciendo: pausa; en pausa: reproduce.
              if (vista.reproduciendo) {
                reproductor.pausar();
              } else {
                reproductor.reproducir();
              }
            }}
          >
            {vista.reproduciendo ? "Pausar" : "Reproducir"}
          </button>
          <button
            type="button"
            onClick={() => {
              soltarManual();
              reproductor.reiniciar();
            }}
          >
            Reiniciar
          </button>

          {/* Un botón por velocidad (1x, 2x, 3x). En modo Servidor, elegir una repite el run guardado
              animado a ese ritmo (el servidor espacia los eventos; un run en curso sigue a su paso). */}
          {VELOCIDADES.map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={vista.velocidad === v}
              onClick={() => {
                soltarManual();
                reproductor.velocidad(v);
              }}
            >
              {v}x
            </button>
          ))}
        </div>

        {/* Seek por índice de evento: 0 = inicio, total = todo aplicado (en vivo, total crece). */}
        <input
          type="range"
          aria-label="Posición en la secuencia de eventos"
          min={0}
          max={vista.total}
          value={vista.aplicados}
          disabled={vista.total === 0}
          onChange={(e) => {
            soltarManual();
            reproductor.irA(Number(e.currentTarget.value));
          }}
        />
        <p className="estado">
          Evento {vista.aplicados} de {vista.total} · slide {estadoVista.slideActivo}
          {vista.terminado ? " · terminado" : ""}
        </p>
      </div>
    </div>
  );
}

// Modo "Grabación local": elige un archivo de contracts/recordings y lo reproduce.
function ModoGrabacion() {
  // Los nombres de grabación se leen una sola vez.
  const nombres = useMemo(() => listarGrabaciones(), []);
  const [nombre, setNombre] = useState(nombres[0] ?? "");

  const [reproductor, setReproductor] = useState<Reproductor | null>(null);
  // Eventos de la grabación elegida (se pasan a la tira de miniaturas).
  const [eventos, setEventos] = useState<readonly Evento[]>([]);
  const [errorGrabacion, setErrorGrabacion] = useState<string | null>(null);
  // Idioma de la guía de la grabación elegida (por defecto español).
  const [idiomaGuia, setIdiomaGuia] = useState<IdiomaFase>("es");

  // Crea el reproductor al elegir una grabación y lo destruye al cambiar o desmontar.
  useEffect(() => {
    // Sin grabaciones disponibles no hay nada que crear.
    if (nombre === "") return;
    let creado: Reproductor | null = null;

    try {
      const lista = cargarGrabacion(nombre).eventos;
      creado = crearReproductor(lista);
      // El idioma de la guía sale de los eventos, así el evento 0 ya lo muestra bien.
      setIdiomaGuia(idiomaDeGuia(lista));
      setEventos(lista);
      setReproductor(creado);
      setErrorGrabacion(null);
    } catch (e) {
      // Una grabación inválida o una secuencia con problemas se muestra, no se oculta.
      setReproductor(null);
      setEventos([]);
      setIdiomaGuia("es");
      setErrorGrabacion(mensaje(e));
    }

    return () => {
      creado?.destruir();
    };
  }, [nombre]);

  return (
    <>
      <label className="selector">
        Grabación
        <select value={nombre} onChange={(e) => setNombre(e.currentTarget.value)}>
          {nombres.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>

      {nombres.length === 0 && <p role="alert">No hay grabaciones en contracts/recordings.</p>}
      {errorGrabacion && <pre role="alert">{errorGrabacion}</pre>}

      {/* La clave por nombre reinicia el lienzo completo al cambiar de grabación. */}
      {reproductor && (
        <Pantalla
          key={nombre}
          reproductor={reproductor}
          idiomaGuia={idiomaGuia}
          eventos={eventos}
        />
      )}
    </>
  );
}

// Pantalla de una fuente en vivo ya creada: estado de la conexión y el lienzo.
function PantallaServidor({ fuente, runId }: { fuente: FuenteEnVivo; runId: string }) {
  const vivo = useEnVivo(fuente);
  // El estado del reductor decide si hay que pedir una aprobación a la persona.
  const estado = useReproductor(fuente).estado;
  // Con el buffer vacío todavía no hay guía de la cual sacar el idioma.
  const idiomaGuia: IdiomaFase = vivo.eventos.length === 0 ? "es" : idiomaDeGuia(vivo.eventos);

  return (
    <>
      <p className="estado" role="status">
        Conexión: {ETIQUETA_CONEXION[vivo.conexion]}
      </p>
      {/* Errores y avisos del canal: visibles, nunca ocultos. */}
      {vivo.mensaje && <pre role="alert">{vivo.mensaje}</pre>}
      {/* Silencio largo con el run abierto (p. ej. espera de cupo de Groq): que no parezca congelado. */}
      <AvisoEspera estado={estado} />
      <Pantalla
        reproductor={fuente}
        idiomaGuia={idiomaGuia}
        eventos={vivo.eventos}
        runFallido={vivo.conexion === "error"}
      />
      {/* Aprobación humana: solo aparece mientras el run espera la decisión (y deja un aviso si se editó algo). */}
      <PanelAprobacion estado={estado} runId={runId} />
    </>
  );
}

// Modo "Servidor": se conecta por SSE a /api/runs/{run_id}/eventos.
function ModoServidor() {
  // Lo que el usuario escribe y el run al que realmente se conecta (solo cambia al enviar).
  const [runEscrito, setRunEscrito] = useState(RUN_POR_DEFECTO);
  const [runActivo, setRunActivo] = useState(RUN_POR_DEFECTO);
  const [fuente, setFuente] = useState<FuenteEnVivo | null>(null);

  // Abre la conexión al cambiar de run y la cierra al cambiar o desmontar.
  useEffect(() => {
    // Sin run no hay nada a lo que conectarse.
    if (runActivo === "") return;
    const creada = crearFuenteEnVivo(`/api/runs/${encodeURIComponent(runActivo)}/eventos`);
    setFuente(creada);
    return () => {
      creada.destruir();
    };
  }, [runActivo]);

  return (
    <>
      <form
        className="selector"
        onSubmit={(e) => {
          e.preventDefault(); // evita recargar la página
          setRunActivo(runEscrito.trim());
        }}
      >
        <label>
          Run ID
          <input value={runEscrito} onChange={(e) => setRunEscrito(e.currentTarget.value)} />
        </label>
        <button type="submit">Conectar</button>
      </form>

      {/* La clave por run reinicia el lienzo completo al cambiar de ejecución. */}
      {fuente && runActivo !== "" && <PantallaServidor key={runActivo} fuente={fuente} runId={runActivo} />}
    </>
  );
}

export function App() {
  const [modo, setModo] = useState<ModoFuente>("grabacion");
  return (
    <main className="app">
      <h1>Lienzo de carruseles</h1>

      <label className="selector">
        Fuente
        <select value={modo} onChange={(e) => setModo(e.currentTarget.value as ModoFuente)}>
          <option value="grabacion">Grabación local</option>
          <option value="servidor">Servidor</option>
        </select>
      </label>

      {/* Cada modo vive en su componente; al cambiar de modo el otro se desmonta y libera su fuente. */}
      {modo === "grabacion" && <ModoGrabacion />}
      {modo === "servidor" && <ModoServidor />}
    </main>
  );
}