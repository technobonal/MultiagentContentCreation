/**
 * Lienzo.tsx — Muestra el SVG de la plantilla y lo pinta con la vista del reproductor.
 * Además de pintar, anima el trabajo de los agentes en vivo:
 *  - borrador del redactor escrito letra por letra (atenuado) y luego solidificado;
 *  - texto del director de arte / correcciones: borrar y reescribir con cursor y nombre;
 *  - transición de color del fondo;
 *  - subrayado de la afirmación que revisa el revisor + tarjeta con la cita;
 *  - letrero de fase (grande al centro mientras el lienzo está vacío, pequeño después);
 *  - avatares flotantes de los agentes que vuelan al lugar donde trabajan.
 * Solo se anima al avanzar de a un evento reproduciendo; con el slider se pinta de golpe.
 */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import gsap from "gsap";
import { AvataresVivos } from "./AvataresVivos.tsx";
import { esperarFuentes, parsearPlantilla } from "./cargarPlantilla.ts";
import { colocarImagenEnVivo, imagenesColocadas, imagenNueva } from "./colocarImagenEnVivo.ts";
import { escribirEnVivo, solidificar } from "./escrituraEnVivo.ts";
import { nombreEspecialidad, detalleDeFase, faseDeEstado, nombreAgente, ultimoEvento } from "./fase.ts";
import type { IdiomaFase } from "./fase.ts";
import { pintarLienzo } from "./pintarLienzo.ts";
import type { CampoActivo } from "./posicionAvatar.ts";
import { resaltarAfirmacion } from "./resaltado.ts";
import { tarjetaDeRevisor } from "./revisor.ts";
import { TarjetaRevisorVista } from "./TarjetaRevisorVista.tsx";
import type { Estado } from "../timeline/types.ts";
import type { VistaReproductor } from "../timeline/reproductor.ts";

// CAMBIO: caracteres por segundo al escribir a 1x (se multiplican por la velocidad: 2x, 3x...).
const CPS_BASE = 40;
// Duración base de la transición del fondo (s); se divide por la velocidad.
const DURACION_FONDO_S = 0.8;

interface PropsLienzo {
  // Estado y reproducción actuales.
  readonly vista: VistaReproductor;
  // Texto del template.svg ya con las rutas de fuentes corregidas.
  readonly svg: string;
  // Idioma de las etiquetas (letrero, agentes, tarjeta, avatares).
  readonly idioma: IdiomaFase;
  // NUEVO (9B-3): el run falló o se cortó sin run_finalizada (opcional; false por defecto).
  readonly runFallido?: boolean;
  // La persona está mirando un slide: sin avatares ni tarjetas encima.
  readonly revisando?: boolean;
}

// Un campo de texto tal como se ve ahora: de qué slide, qué texto y si es borrador.
interface CampoVisible {
  readonly slide: number;
  readonly campo: string;
  readonly texto: string;
  readonly borrador: boolean;
}

// Recoge todos los textos visibles del estado: primero borradores, luego los dibujados (que ganan).
function textosVisibles(estado: Estado): Map<string, CampoVisible> {
  const mapa = new Map<string, CampoVisible>();

  // Capa borrador (redactor).
  for (const [slideTxt, campos] of Object.entries(estado.propuestas)) {
    // Un ciclo por campo propuesto del slide.
    for (const [campo, texto] of Object.entries(campos)) {
      mapa.set(`${slideTxt}:${campo}`, { slide: Number(slideTxt), campo, texto, borrador: true });
    }
  }
  // Capa dibujada: reemplaza al borrador del mismo campo.
  for (const [slideTxt, campos] of Object.entries(estado.lienzo.textos)) {
    for (const [campo, texto] of Object.entries(campos)) {
      mapa.set(`${slideTxt}:${campo}`, { slide: Number(slideTxt), campo, texto, borrador: false });
    }
  }
  return mapa;
}

// true mientras no hay ningún texto (ni borrador ni dibujado): el lienzo está "vacío".
function lienzoVacio(estado: Estado): boolean {
  return (
    Object.keys(estado.lienzo.textos).length === 0 && Object.keys(estado.propuestas).length === 0
  );
}

export function Lienzo({ vista, svg, idioma, runFallido = false, revisando = false }: PropsLienzo) {
  const contenedor = useRef<HTMLDivElement | null>(null);
  const marco = useRef<HTMLDivElement | null>(null);
  const etiquetaCursor = useRef<HTMLDivElement | null>(null);
  const [montado, setMontado] = useState(false);
  const [fuentesListas, setFuentesListas] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Campo sobre el que acaba de trabajar un agente (para ubicar su avatar).
  const [campoActivo, setCampoActivo] = useState<CampoActivo | null>(null);

  // Textos visibles del último pintado, para detectar qué cambió.
  const textosPrevios = useRef<Map<string, CampoVisible>>(new Map());
  // Borradores del redactor del último pintado ("slide:campo" -> texto).
  const propuestasPrevias = useRef<Map<string, string>>(new Map());
  // seq del último pintado y si se venía reproduciendo (para decidir si se anima).
  const seqPrevio = useRef(0);
  const veniaReproduciendo = useRef(false);
  // Evento cuya afirmación ya se subrayó (para animar el barrido solo una vez).
  const claveResaltada = useRef<string | null>(null);
  // Animación de escritura / solidificación en curso.
  const animacion = useRef<gsap.core.Timeline | null>(null);
  // Imágenes ya dibujadas («slide:campo» -> referencia) y cómo deshacer la animación de la foto en curso.
  const imagenesPrevias = useRef<Map<string, string>>(new Map());
  const restaurarImagen = useRef<(() => void) | null>(null);

  // Monta el SVG una vez por plantilla y espera las tipografías antes de medir.
  useEffect(() => {
    const cont = contenedor.current;
    if (!cont) return;
    let cancelado = false;

    try {
      const raiz = parsearPlantilla(svg);
      cont.replaceChildren(document.importNode(raiz, true));

      // El SVG se adapta al ancho del contenedor; el viewBox mantiene la proporción.
      const svgEl = cont.querySelector("svg");
      if (svgEl) {
        svgEl.removeAttribute("width");
        svgEl.removeAttribute("height");
        svgEl.style.width = "100%";
        svgEl.style.height = "auto";
        svgEl.style.display = "block";
      }
      setError(null);
      setMontado(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return;
    }

    // Cuando las fuentes terminan, se vuelve a pintar para medir con la tipografía real.
    void esperarFuentes().then(() => {
      if (!cancelado) setFuentesListas(true);
    });

    // Al desmontar se cortan las animaciones, se limpia el SVG y se reinician los registros.
    return () => {
      cancelado = true;
      animacion.current?.kill();
      animacion.current = null;
      gsap.killTweensOf(cont.querySelectorAll("#fondo"));
      cont.replaceChildren();
      setMontado(false);
      setFuentesListas(false);
      setCampoActivo(null);
      textosPrevios.current = new Map();
      propuestasPrevias.current = new Map();
      seqPrevio.current = 0;
      veniaReproduciendo.current = false;
      claveResaltada.current = null;
      imagenesPrevias.current = new Map();
      restaurarImagen.current = null;
    };
  }, [svg]);

  // Pinta en cada cambio de estado y anima lo que acaba de hacer el agente.
  useLayoutEffect(() => {
    const cont = contenedor.current;
    const marcoEl = marco.current;
    const etiqueta = etiquetaCursor.current;
    if (!cont || !marcoEl || !etiqueta || !montado) return;

    // Se corta la animación del evento anterior y se oculta su etiqueta. Si era la de una foto, se deshace primero
    // (si no, la foto quedaría a medio revelar con los estilos de la animación).
    restaurarImagen.current?.();
    restaurarImagen.current = null;
    animacion.current?.kill();
    animacion.current = null;
    gsap.killTweensOf(etiqueta);
    gsap.set(etiqueta, { opacity: 0 });

    // El fondo se lee antes de pintar para animar el cambio de color.
    const fondoEl = cont.querySelector<SVGElement>("#fondo");
    let fondoAntes: string | null = null;
    if (fondoEl) {
      gsap.killTweensOf(fondoEl);
      fondoEl.style.removeProperty("fill");
      fondoAntes = fondoEl.getAttribute("fill");
    }

    // Pinta el estado completo (con borradores del redactor).
    pintarLienzo(cont, vista.estado, undefined, { borradores: true });

    // Se anima solo al avanzar exactamente un evento reproduciendo, sin "reducir movimiento".
    const reducirMovimiento =
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const salto = vista.estado.ultimoSeq - seqPrevio.current;
    const animar =
      (vista.reproduciendo || veniaReproduciendo.current) && salto === 1 && !reducirMovimiento && !revisando;
    seqPrevio.current = vista.estado.ultimoSeq;
    veniaReproduciendo.current = vista.reproduciendo;

    // Transición de color del fondo (el atributo ya tiene el color nuevo).
    if (animar && fondoEl && fondoAntes !== null) {
      const fondoDespues = fondoEl.getAttribute("fill");
      // Solo si el color realmente cambió.
      if (fondoDespues !== null && fondoDespues !== fondoAntes) {
        gsap.fromTo(
          fondoEl,
          { fill: fondoAntes },
          {
            fill: fondoDespues,
            duration: DURACION_FONDO_S / vista.velocidad,
            ease: "power1.inOut",
            clearProps: "fill",
          },
        );
      }
    }

    // Qué textos cambiaron respecto al pintado anterior (solo del slide activo).
    const actuales = textosVisibles(vista.estado);
    let elegido: { campo: CampoVisible; previo: CampoVisible | undefined } | null = null;

    // Un ciclo por campo visible; se queda con el último que cambió.
    for (const [clave, ahora] of actuales) {
      const antes = textosPrevios.current.get(clave);
      const igual = antes !== undefined && antes.texto === ahora.texto && antes.borrador === ahora.borrador;
      // Sin cambios, o en un slide que no se ve: no hay nada que animar.
      if (igual || ahora.slide !== vista.estado.slideActivo) continue;
      elegido = { campo: ahora, previo: antes };
    }
    textosPrevios.current = actuales;

    // Qué borrador del redactor cambió (aunque no se vea): sirve para ubicar a su avatar.
    let propuestaCambiada: CampoActivo | null = null;
    const propuestasAhora = new Map<string, string>();
    for (const [slideTxt, campos] of Object.entries(vista.estado.propuestas)) {
      // Un ciclo por campo propuesto del slide.
      for (const [campo, texto] of Object.entries(campos)) {
        const clave = `${slideTxt}:${campo}`;
        propuestasAhora.set(clave, texto);
        // Sin cambios, o en un slide que no se ve: se ignora.
        if (propuestasPrevias.current.get(clave) === texto) continue;
        if (Number(slideTxt) !== vista.estado.slideActivo) continue;
        propuestaCambiada = { slide: Number(slideTxt), campo };
      }
    }
    propuestasPrevias.current = propuestasAhora;

    // Qué foto apareció en el slide activo (para ubicar a su avatar y animarla).
    const imagenesAhora = imagenesColocadas(vista.estado);
    const fotoNueva = imagenNueva(imagenesPrevias.current, imagenesAhora, vista.estado.slideActivo);
    imagenesPrevias.current = imagenesAhora;

    // El campo de trabajo es la foto nueva, el texto que cambió en pantalla o, si no, el borrador que cambió.
    const ubicacion: CampoActivo | null =
      fotoNueva !== null
        ? fotoNueva
        : elegido !== null
          ? { slide: elegido.campo.slide, campo: elegido.campo.campo }
          : propuestaCambiada;
    // Solo se actualiza el estado si el campo realmente cambió (evita renders de más).
    if (ubicacion !== null) {
      setCampoActivo((prev) =>
        prev !== null && prev.slide === ubicacion.slide && prev.campo === ubicacion.campo
          ? prev
          : ubicacion,
      );
    }

    // Una foto recién colocada se anima con su propia coreografía y deja sin animar al texto de ese instante.
    const ultimoEv = ultimoEvento(vista.estado);
    let animoFoto = false;
    if (animar && fotoNueva !== null && ultimoEv?.tipo === "colocar_imagen") {
      const grupo = cont.querySelector<SVGElement>(`#slide-${fotoNueva.slide} [data-campo="{{${fotoNueva.campo}}}"]`);
      if (grupo) {
        const colocacion = colocarImagenEnVivo({
          grupo,
          marco: marcoEl,
          agente: ultimoEv.agente ?? "director_arte",
          nombreAgente: nombreAgente(ultimoEv.agente ?? "director_arte", idioma),
          especialidad: nombreEspecialidad("fotografia", idioma),
          descripcion: vista.estado.lienzo.imagenes[fotoNueva.slide]?.[fotoNueva.campo]?.texto_alternativo ?? "foto de la fuente",
          slide: fotoNueva.slide,
          velocidad: vista.velocidad,
        });
        animacion.current = colocacion.timeline;
        restaurarImagen.current = colocacion.restaurar;
        animoFoto = true;
      }
    }

    // Anima el campo elegido con el nombre del agente que hizo el último evento.
    if (animar && elegido !== null && !animoFoto) {
      const { campo, previo } = elegido;
      const div = cont.querySelector<HTMLElement>(
        `#slide-${campo.slide} [data-campo="{{${campo.campo}}}"] div`,
      );
      const ultimo = ultimoEvento(vista.estado);
      const nombre = nombreAgente(ultimo?.agente ?? "redactor", idioma);

      if (div) {
        // Mismo texto que el borrador, ahora definitivo: solo se solidifica.
        if (previo !== undefined && previo.borrador && !campo.borrador && previo.texto === campo.texto) {
          animacion.current = solidificar({
            div,
            etiqueta,
            marco: marcoEl,
            nombreAgente: nombre,
            velocidad: vista.velocidad,
          });
        } else {
          // Texto nuevo o distinto: se borra el anterior (si lo había) y se escribe en vivo.
          animacion.current = escribirEnVivo({
            div,
            texto: campo.texto,
            textoPrevio: previo === undefined ? null : previo.texto,
            caracteresPorSegundo: CPS_BASE * vista.velocidad,
            // NUEVO: la velocidad también acorta el borrado, la pausa final y el desvanecimiento.
            velocidad: vista.velocidad,
            etiqueta,
            marco: marcoEl,
            nombreAgente: nombre,
          });
        }
      }
    }

    // Subrayado del revisor sobre la afirmación que acaba de verificar.
    const tarjeta = tarjetaDeRevisor(vista.estado, idioma);
    if (
      tarjeta !== null &&
      tarjeta.afirmacion !== null &&
      tarjeta.slide !== null &&
      tarjeta.slide === vista.estado.slideActivo
    ) {
      // El barrido de entrada solo se anima la primera vez que se muestra este evento.
      const nueva = animar && claveResaltada.current !== tarjeta.clave;
      resaltarAfirmacion(cont, tarjeta.slide, tarjeta.afirmacion, tarjeta.tono, nueva);
      claveResaltada.current = tarjeta.clave;
    } else {
      claveResaltada.current = null;
    }
  }, [vista.estado, vista.reproduciendo, vista.velocidad, montado, fuentesListas, idioma, revisando]);

  // Al desmontar el componente se corta cualquier animación pendiente.
  useEffect(() => {
    return () => {
      animacion.current?.kill();
    };
  }, []);

  // Datos del letrero y la tarjeta.
  const fase = faseDeEstado(vista.estado, idioma);
  const detalle = detalleDeFase(vista.estado, idioma);
  const ultimo = ultimoEvento(vista.estado);
  const agente = ultimo === null ? null : nombreAgente(ultimo.agente, idioma);
  const vacio = lienzoVacio(vista.estado);
  const tarjeta = tarjetaDeRevisor(vista.estado, idioma);

  // Error de carga o de parseo: mensaje visible en vez de un lienzo vacío.
  if (error) {
    return <p role="alert">No se pudo mostrar el lienzo: {error}</p>;
  }

  return (
    <div ref={marco} className={`lienzo-marco${revisando ? " lienzo-revisando" : ""}`}>
      <div ref={contenedor} className="lienzo" role="img" aria-label="Vista previa del carrusel" />

      {/* Letrero de fase: grande y centrado con el lienzo vacío, pequeño arriba después. */}
      <div className={`letrero ${vacio ? "letrero-grande" : "letrero-chico"}`} aria-live="polite">
        {agente !== null && <span className="letrero-agente">{agente}</span>}
        <p key={fase} className="letrero-titulo">
          {fase}
        </p>
        {vacio && detalle !== null && (
          <p key={detalle} className="letrero-detalle">
            {detalle}
          </p>
        )}
      </div>

      {/* Etiqueta flotante con el nombre del agente que escribe (se mueve con el cursor). */}
      <div ref={etiquetaCursor} className="cursor-etiqueta" aria-hidden="true" />

      {/* Tarjeta del revisor; la clave reinicia su animación en cada evento. */}
      {tarjeta !== null && <TarjetaRevisorVista key={tarjeta.clave} tarjeta={tarjeta} />}

      {/* Avatares de los agentes: reposan en el borde y el activo vuela a trabajar. */}
      <AvataresVivos
        estado={vista.estado}
        idioma={idioma}
        marco={marco}
        campoActivo={campoActivo}
        reproduciendo={vista.reproduciendo}
        velocidad={vista.velocidad}
        runFallido={runFallido}
      />
    </div>
  );
}