/**
 * App.tsx — Pantalla provisional del paso 4a: elige una grabación, carga la plantilla,
 * crea el reproductor y muestra la mesa de agentes, el lienzo y controles mínimos.
 * El idioma de las etiquetas es el de la guía salvo que el usuario elija otro.
 * Los controles definitivos llegan en el paso 4b.
 */
import { useEffect, useMemo, useState } from "react";
import { cargarGrabacion, listarGrabaciones } from "./lib/grabacion.ts";
import { cargarPlantillaSvg } from "./lienzo/cargarPlantilla.ts";
import { idiomaDeGuia, leerEleccion } from "./lienzo/fase.ts";
import type { EleccionIdioma, IdiomaFase } from "./lienzo/fase.ts";
import { Lienzo } from "./lienzo/Lienzo.tsx";
import { MesaAgentes } from "./lienzo/MesaAgentes.tsx";
// NUEVO: tira de miniaturas, una por slide.
import { TiraMiniaturas } from "./lienzo/TiraMiniaturas.tsx";
import { useReproductor } from "./lienzo/useReproductor.ts";
// Las velocidades salen del reproductor (única fuente de verdad); no hay lista local.
import { VELOCIDADES, crearReproductor } from "./timeline/reproductor.ts";
import type { Reproductor } from "./timeline/reproductor.ts";
// NUEVO: tipo de los eventos, para pasarlos a la tira.
import type { Evento } from "./timeline/types.ts";

// Convierte cualquier error en un texto legible.
function mensaje(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

// Mesa de agentes, lienzo, miniaturas y controles de un reproductor ya creado.
function Pantalla({
  reproductor,
  svg,
  idiomaGuia,
  eventos,
}: {
  reproductor: Reproductor;
  svg: string;
  idiomaGuia: IdiomaFase;
  // NUEVO: eventos de la grabación (la tira calcula a dónde saltar con ellos).
  eventos: readonly Evento[];
}) {
  const vista = useReproductor(reproductor);

  // "auto" = idioma de la guía; si el usuario elige otro, manda su elección.
  // Esta pantalla se remonta al cambiar de grabación (key), así que vuelve a "auto".
  const [eleccion, setEleccion] = useState<EleccionIdioma>("auto");
  const idioma: IdiomaFase = eleccion === "auto" ? idiomaGuia : eleccion;

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

      <Lienzo vista={vista} svg={svg} idioma={idioma} />

      {/* NUEVO: miniaturas; al hacer clic se salta al punto donde ese slide ya tiene contenido. */}
      <TiraMiniaturas
        svg={svg}
        estado={vista.estado}
        eventos={eventos}
        idioma={idioma}
        onIrA={(indice) => reproductor.irA(indice)}
      />

      <div className="controles">
        <div className="fila">
          {/* Alterna entre reproducir y pausar según el estado actual. */}
          <button
            type="button"
            onClick={() => (vista.reproduciendo ? reproductor.pausar() : reproductor.reproducir())}
          >
            {vista.reproduciendo ? "Pausar" : "Reproducir"}
          </button>
          <button type="button" onClick={() => reproductor.reiniciar()}>
            Reiniciar
          </button>

          {/* Un botón por velocidad (1x, 2x, 3x); el activo se marca con aria-pressed. */}
          {VELOCIDADES.map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={vista.velocidad === v}
              onClick={() => reproductor.velocidad(v)}
            >
              {v}x
            </button>
          ))}
        </div>

        {/* Seek por índice de evento: 0 = inicio, total = todo aplicado. */}
        <input
          type="range"
          aria-label="Posición en la secuencia de eventos"
          min={0}
          max={vista.total}
          value={vista.aplicados}
          disabled={vista.total === 0}
          onChange={(e) => reproductor.irA(Number(e.currentTarget.value))}
        />
        <p className="estado">
          Evento {vista.aplicados} de {vista.total} · slide {vista.estado.slideActivo}
          {vista.terminado ? " · terminado" : ""}
        </p>
      </div>
    </div>
  );
}

export function App() {
  // Los nombres de grabación se leen una sola vez.
  const nombres = useMemo(() => listarGrabaciones(), []);
  const [nombre, setNombre] = useState(nombres[0] ?? "");

  const [svg, setSvg] = useState<string | null>(null);
  const [errorSvg, setErrorSvg] = useState<string | null>(null);
  const [reproductor, setReproductor] = useState<Reproductor | null>(null);
  // NUEVO: eventos de la grabación elegida (se pasan a la tira de miniaturas).
  const [eventos, setEventos] = useState<readonly Evento[]>([]);
  const [errorGrabacion, setErrorGrabacion] = useState<string | null>(null);
  // Idioma de la guía de la grabación elegida (por defecto español).
  const [idiomaGuia, setIdiomaGuia] = useState<IdiomaFase>("es");

  // Carga la plantilla una vez.
  useEffect(() => {
    let cancelado = false;
    cargarPlantillaSvg()
      .then((texto) => {
        // Si el componente se desmontó mientras llegaba la respuesta, se descarta.
        if (!cancelado) setSvg(texto);
      })
      .catch((e: unknown) => {
        if (!cancelado) setErrorSvg(mensaje(e));
      });
    return () => {
      cancelado = true;
    };
  }, []);

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
    <main className="app">
      <h1>Lienzo de carruseles</h1>

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
      {errorSvg && <p role="alert">No se pudo cargar la plantilla: {errorSvg}</p>}
      {errorGrabacion && <pre role="alert">{errorGrabacion}</pre>}
      {!svg && !errorSvg && <p>Cargando plantilla…</p>}

      {/* La clave por nombre reinicia el lienzo completo al cambiar de grabación. */}
      {svg && reproductor && (
        <Pantalla
          key={nombre}
          reproductor={reproductor}
          svg={svg}
          idiomaGuia={idiomaGuia}
          eventos={eventos}
        />
      )}
    </main>
  );
}