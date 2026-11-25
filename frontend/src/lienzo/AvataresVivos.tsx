/**
 * AvataresVivos.tsx — Capa flotante sobre el lienzo con los avatares de los agentes.
 * Los inactivos esperan en una fila al borde inferior y flotan suavemente. El activo
 * vuela hasta su lugar de trabajo (junto al cursor de escritura, la afirmación subrayada,
 * una esquina para pintar el fondo o el centro) y muestra una burbuja con su actividad.
 * Una función por cuadro (gsap.ticker) mueve los avatares; así siguen al cursor mientras
 * se escribe. Con el slider, o con "reducir movimiento", se colocan de golpe.
 *
 * Cierre del run (9B-3): la burbuja de cierre dura MS_BURBUJA_CIERRE y después todos los
 * avatares vuelven a reposo sin burbuja. En un run exitoso es «Cerrando la ejecución…»
 * (con "reducir movimiento" se pasa directo al reposo); en un run fallido (`runFallido`)
 * el avatar del último evento vuelve a reposo con una burbuja de fallo.
 */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import gsap from "gsap";
import { AGENTES_AVATAR, Avatar } from "./avatares.tsx";
import type { IdiomaFase } from "./fase.ts";
import { actividadDeEstado } from "./posicionAvatar.ts";
import type { ActividadAvatar, CampoActivo } from "./posicionAvatar.ts";
import type { Estado } from "../timeline/types.ts";

// Lado de cada avatar en px.
const TAM = 44;
// Separación entre avatares en la fila de reposo y margen al borde (px).
const SEPARACION = 50;
const MARGEN = 10;
// Fracción de la distancia que recorre el avatar en cada cuadro al volar (a 1x).
const SUAVIDAD = 0.14;
// Cuánto se ve la burbuja de cierre antes de dejar los avatares en reposo (ms).
export const MS_BURBUJA_CIERRE = 3000;

// Referencia a un elemento (compatible con useRef de React 18 y 19).
interface Ref<T> {
  readonly current: T | null;
}

interface PropsAvatares {
  readonly estado: Estado;
  readonly idioma: IdiomaFase;
  // Marco del lienzo: el que posiciona las capas y contiene el SVG.
  readonly marco: Ref<HTMLDivElement>;
  // Campo de texto sobre el que se trabaja (lo calcula Lienzo al pintar).
  readonly campoActivo: CampoActivo | null;
  readonly reproduciendo: boolean;
  readonly velocidad: number;
  // El run falló o se cortó sin run_finalizada (opcional; false por defecto).
  readonly runFallido?: boolean;
}

// Punto (esquina superior izquierda del avatar) en coordenadas del marco.
interface Punto {
  x: number;
  y: number;
}

// Datos que el bucle por cuadro necesita leer sin volver a renderizar.
interface DatosVivos {
  actividad: ActividadAvatar | null;
  campoActivo: CampoActivo | null;
  slide: number;
  // true = volar suavemente; false = colocar de golpe.
  suave: boolean;
  velocidad: number;
}

// Mantiene un punto dentro del marco para que el avatar nunca se salga.
function limitar(p: Punto, ancho: number, alto: number): Punto {
  return {
    x: Math.max(0, Math.min(p.x, ancho - TAM)),
    y: Math.max(0, Math.min(p.y, alto - TAM)),
  };
}

// Lugar de reposo de un agente: su casilla en la fila del borde inferior.
function puntoDeReposo(agente: string, alto: number): Punto {
  const indice = Math.max(0, AGENTES_AVATAR.indexOf(agente));
  return { x: MARGEN + indice * SEPARACION, y: alto - TAM - 8 };
}

// Busca el <div> de un campo de texto del slide (o el primero si no se da el nombre).
function buscarCampo(marco: HTMLElement, slide: number, campo: string | null): HTMLElement | null {
  const selector =
    campo !== null ? `#slide-${slide} [data-campo="{{${campo}}}"] div` : `#slide-${slide} [data-campo] div`;
  return marco.querySelector<HTMLElement>(selector);
}

// true si el rectángulo existe de verdad (un elemento oculto mide 0 × 0).
function tieneTamano(r: DOMRect): boolean {
  return r.width > 0 || r.height > 0;
}

// Lugar de trabajo del avatar activo, según el destino de su actividad.
function puntoDeTrabajo(
  marcoEl: HTMLElement,
  m: DOMRect,
  actividad: ActividadAvatar,
  campoActivo: CampoActivo | null,
  slide: number,
): Punto {
  // Centro (algo por encima del medio, para no tapar el letrero grande).
  const centro = limitar({ x: m.width / 2 - TAM / 2, y: m.height * 0.2 }, m.width, m.height);

  switch (actividad.destino) {
    case "reposo":
      // Run fallido: el avatar se queda en su casilla de reposo (con la burbuja de fallo).
      return puntoDeReposo(actividad.agente, m.height);

    case "esquina":
      // Pintar el fondo: esquina superior derecha.
      return limitar({ x: m.width - TAM - 14, y: 14 }, m.width, m.height);

    case "campo": {
      // Si se está escribiendo, el avatar sigue al cursor.
      const cursor = marcoEl.querySelector<HTMLElement>(".cursor-vivo");
      if (cursor) {
        const r = cursor.getBoundingClientRect();
        return limitar({ x: r.left - m.left + 10, y: r.bottom - m.top + 4 }, m.width, m.height);
      }
      // Sin cursor: arriba a la derecha del campo (solo si ese campo es del slide visible).
      const nombre = campoActivo !== null && campoActivo.slide === slide ? campoActivo.campo : null;
      const campo = buscarCampo(marcoEl, slide, nombre);
      if (!campo) return centro;
      const r = campo.getBoundingClientRect();
      // Campo oculto o sin medida: se vuelve al centro.
      if (!tieneTamano(r)) return centro;
      return limitar({ x: r.right - m.left - TAM, y: r.top - m.top - TAM - 6 }, m.width, m.height);
    }

    case "afirmacion": {
      // El revisor se posa bajo la afirmación subrayada.
      const marca = marcoEl.querySelector<HTMLElement>(".marca-revisor");
      if (marca) {
        const r = marca.getBoundingClientRect();
        if (tieneTamano(r)) {
          return limitar({ x: r.right - m.left - 12, y: r.bottom - m.top + 6 }, m.width, m.height);
        }
      }
      // Sin subrayado: junto al cuerpo del slide, o al centro si tampoco hay.
      const cuerpo = buscarCampo(marcoEl, slide, "cuerpo");
      if (!cuerpo) return centro;
      const r = cuerpo.getBoundingClientRect();
      if (!tieneTamano(r)) return centro;
      return limitar({ x: r.right - m.left - TAM, y: r.top - m.top - TAM - 6 }, m.width, m.height);
    }

    default:
      return centro;
  }
}

export function AvataresVivos({
  estado,
  idioma,
  marco,
  campoActivo,
  reproduciendo,
  velocidad,
  runFallido = false,
}: PropsAvatares) {
  // Actividad del último evento (o la de fallo si el run se cortó), tal como la describe la función pura.
  const actividadPura = actividadDeEstado(estado, idioma, runFallido);
  const clave = actividadPura !== null ? actividadPura.clave : null;
  const cierre = actividadPura !== null ? actividadPura.cierre : null;

  // Clave del cierre cuya burbuja ya venció (null = ninguna): pasados unos segundos se oculta.
  const [cierreVencido, setCierreVencido] = useState<string | null>(null);

  // Temporizador de la burbuja de cierre.
  useEffect(() => {
    // Sin cierre en pantalla se olvida el cierre vencido: el próximo cierre vuelve a mostrarse.
    if (clave === null || cierre === null) {
      setCierreVencido(null);
      return;
    }
    const temporizador = window.setTimeout(() => setCierreVencido(clave), MS_BURBUJA_CIERRE);
    return () => {
      window.clearTimeout(temporizador);
    };
  }, [clave, cierre]);

  // Con "reducir movimiento" el cierre exitoso pasa directo al reposo (el de fallo sí muestra su aviso).
  const reducirMovimiento = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  const ocultarCierre =
    cierre !== null && ((cierre === "exitoso" && reducirMovimiento) || cierreVencido === clave);
  // Cierre ya vencido: sin actividad, así todos los avatares vuelven a su casilla y sin burbuja.
  const actividad = ocultarCierre ? null : actividadPura;

  // Elemento y posición actual de cada avatar.
  const elementos = useRef(new Map<string, HTMLDivElement>());
  const posiciones = useRef(new Map<string, Punto>());
  // Datos que lee el bucle por cuadro (se actualizan en cada render).
  const vivo = useRef<DatosVivos>({
    actividad,
    campoActivo,
    slide: estado.slideActivo,
    suave: false,
    velocidad,
  });
  // Último seq visto: sirve para saber si se avanzó de a un evento.
  const seqPrevio = useRef(0);

  // Actualiza los datos del bucle y decide si el avatar vuela o se coloca de golpe.
  useLayoutEffect(() => {
    const salto = estado.ultimoSeq - seqPrevio.current;
    seqPrevio.current = estado.ultimoSeq;
    const reducir = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

    // Solo se recalcula cuando cambió el evento: así un re-render no corta un vuelo en curso.
    if (salto !== 0) {
      vivo.current.suave = reproduciendo && salto === 1 && !reducir;
    }
    vivo.current.actividad = actividad;
    vivo.current.campoActivo = campoActivo;
    vivo.current.slide = estado.slideActivo;
    vivo.current.velocidad = velocidad;
  });

  // Bucle por cuadro: acerca cada avatar a su destino (el activo, al trabajo; el resto, al reposo).
  useEffect(() => {
    const cuadro = (): void => {
      const marcoEl = marco.current;
      if (!marcoEl) return;
      const m = marcoEl.getBoundingClientRect();
      // Marco aún sin medida (oculto o recién montado): no hay nada que mover.
      if (m.width === 0) return;

      const datos = vivo.current;
      const k = datos.suave ? Math.min(1, SUAVIDAD * datos.velocidad) : 1;
      const trabajo =
        datos.actividad !== null
          ? puntoDeTrabajo(marcoEl, m, datos.actividad, datos.campoActivo, datos.slide)
          : null;

      // Un avatar por agente.
      for (const agente of AGENTES_AVATAR) {
        const el = elementos.current.get(agente);
        if (!el) continue;

        // El activo va al trabajo; los demás, a su casilla de reposo.
        const esActivo = datos.actividad !== null && datos.actividad.agente === agente;
        const meta = esActivo && trabajo !== null ? trabajo : puntoDeReposo(agente, m.height);

        // La primera vez aparece directamente en su sitio.
        let p = posiciones.current.get(agente);
        if (!p) {
          p = { x: meta.x, y: meta.y };
          posiciones.current.set(agente, p);
        }
        p.x += (meta.x - p.x) * k;
        p.y += (meta.y - p.y) * k;

        el.style.transform = `translate(${p.x.toFixed(1)}px, ${p.y.toFixed(1)}px)`;
        // La burbuja se abre hacia el lado con más espacio.
        el.dataset.lado = p.x > m.width / 2 ? "izq" : "der";
      }
    };

    gsap.ticker.add(cuadro);
    return () => {
      gsap.ticker.remove(cuadro);
    };
  }, [marco]);

  return (
    <div className="avatares" aria-hidden="true">
      {/* Un avatar por agente; el del último evento va resaltado y con burbuja. */}
      {AGENTES_AVATAR.map((agente, i) => {
        const propia = actividad !== null && actividad.agente === agente ? actividad : null;
        // El sistema solo se ve cuando actúa.
        const clase = [
          "avatar",
          propia !== null ? "avatar-activo" : "",
          agente === "sistema" && propia === null ? "avatar-oculto" : "",
        ]
          .filter(Boolean)
          .join(" ");

        return (
          <div
            key={agente}
            ref={(el) => {
              // Se registra el elemento al montar y se olvida al desmontar.
              if (el) elementos.current.set(agente, el);
              else elementos.current.delete(agente);
            }}
            className={clase}
            data-accion={propia !== null ? propia.accion : "reposo"}
          >
            {/* El cuerpo flota con un desfase distinto por agente. */}
            <div className="avatar-cuerpo" style={{ animationDelay: `${-i * 0.6}s` }}>
              <Avatar agente={agente} tamano={TAM} />
            </div>

            {/* Burbuja de actividad; la clave reinicia su animación en cada evento. */}
            {propia !== null && (
              <span key={propia.clave} className="avatar-burbuja">
                {propia.burbuja}
              </span>
            )}

            {/* Burbujitas de pensamiento mientras el estratega planifica. */}
            {propia !== null && propia.accion === "pensar" && (
              <span className="pensando">
                <i />
                <i />
                <i />
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}