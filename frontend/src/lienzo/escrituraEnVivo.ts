// ---------------------------------------------------------------------------
// escrituraEnVivo.ts — Animaciones de los agentes sobre un campo de texto:
//  - escribirEnVivo: borra el texto anterior (si había) y escribe el nuevo letra
//    por letra con un cursor y una etiqueta con el nombre del agente.
//  - solidificar: el borrador pasa a texto definitivo (sin reescribir).
// El texto completo siempre está en el DOM (la parte aún no escrita va invisible),
// así que los saltos de línea y el tamaño ya medidos no cambian mientras se escribe.
// ---------------------------------------------------------------------------
import gsap from "gsap";

// Pausa con el cursor al final antes de retirarlo (s, a 1x; se divide por la velocidad).
const PAUSA_FINAL_S = 0.5;
// Duración del desvanecimiento de la etiqueta (s, a 1x; se divide por la velocidad).
const DESVANECER_S = 0.25;
// Velocidad y tope del borrado del texto anterior (a 1x; el tiempo se divide por la velocidad).
const CPS_BORRADO = 160;
const MAX_BORRADO_S = 0.45;
// Duración base de la solidificación (s); se divide por la velocidad.
const DURACION_SOLIDIFICAR_S = 0.6;

// Opciones de escribirEnVivo.
export interface OpcionesEscritura {
  // <div> del campo dentro del foreignObject.
  readonly div: HTMLElement;
  readonly texto: string;
  // Texto que había antes (se borra primero); null si el campo estaba vacío.
  readonly textoPrevio: string | null;
  // Caracteres por segundo ya multiplicados por la velocidad.
  readonly caracteresPorSegundo: number;
  // NUEVO: velocidad de reproducción (1, 2, 3...). Acorta el borrado, la pausa final
  // y el desvanecimiento para que la animación quepa antes del siguiente evento.
  // Opcional: si falta se asume 1x, así que no rompe a quien ya llamaba sin ella.
  readonly velocidad?: number;
  // Etiqueta flotante y contenedor sobre el que se posiciona.
  readonly etiqueta: HTMLElement;
  readonly marco: HTMLElement;
  readonly nombreAgente: string;
}

// Opciones de solidificar.
export interface OpcionesSolidificar {
  readonly div: HTMLElement;
  readonly etiqueta: HTMLElement;
  readonly marco: HTMLElement;
  readonly nombreAgente: string;
  readonly velocidad: number;
}

// Parte un texto en caracteres completos (respeta emojis y pares sustitutos).
function partir(texto: string): string[] {
  return Array.from(texto);
}

// Coloca la etiqueta flotante con su esquina inferior izquierda en (x, y) del marco.
export function colocarEtiqueta(etiqueta: HTMLElement, marco: HTMLElement, x: number, y: number): void {
  const anchoMarco = marco.getBoundingClientRect().width;
  // La etiqueta no se sale por la derecha ni por arriba.
  const izquierda = Math.max(0, Math.min(x, anchoMarco - etiqueta.offsetWidth));
  const arriba = Math.max(0, y - etiqueta.offsetHeight - 4);
  etiqueta.style.transform = `translate(${izquierda}px, ${arriba}px)`;
}

// Escribe `texto` en el campo letra por letra; devuelve la línea de tiempo para poder cortarla.
export function escribirEnVivo(o: OpcionesEscritura): gsap.core.Timeline {
  const { div, texto, textoPrevio, etiqueta, marco, nombreAgente } = o;
  const velocidad = Math.max(1, o.caracteresPorSegundo);
  // NUEVO: factor de aceleración para los tiempos fijos (nunca 0 ni negativo).
  const factor = Math.max(0.1, o.velocidad ?? 1);
  const letrasNuevas = partir(texto);
  const letrasPrevias = textoPrevio !== null ? partir(textoPrevio) : [];
  const hayPrevio = letrasPrevias.length > 0;

  // Texto que se está mostrando ahora: el previo mientras se borra, el nuevo al escribir.
  let letras = hayPrevio ? letrasPrevias : letrasNuevas;

  // Estructura: [texto visible][cursor][resto invisible].
  const visible = document.createTextNode("");
  const cursor = document.createElement("span");
  cursor.className = "cursor-vivo";
  const oculto = document.createElement("span");
  oculto.className = "texto-oculto";
  div.replaceChildren(visible, cursor, oculto);

  // La etiqueta sigue al cursor (esquina superior izquierda del cursor).
  function seguirCursor(): void {
    const c = cursor.getBoundingClientRect();
    const m = marco.getBoundingClientRect();
    colocarEtiqueta(etiqueta, marco, c.left - m.left, c.top - m.top);
  }

  // Muestra los primeros n caracteres y deja el resto invisible.
  function pintar(n: number): void {
    const k = Math.max(0, Math.min(letras.length, Math.round(n)));
    visible.data = letras.slice(0, k).join("");
    oculto.textContent = letras.slice(k).join("");
    seguirCursor();
  }

  etiqueta.textContent = nombreAgente;
  gsap.set(etiqueta, { opacity: 1 });

  const progreso = { n: hayPrevio ? letrasPrevias.length : 0 };
  pintar(progreso.n);

  const tl = gsap.timeline();

  // Fase 1 (solo si había texto): se borra el anterior rápido.
  if (hayPrevio) {
    tl.fromTo(
      progreso,
      { n: letrasPrevias.length },
      {
        n: 0,
        // CAMBIO: la duración del borrado se divide por la velocidad.
        duration: Math.min(MAX_BORRADO_S, letrasPrevias.length / CPS_BORRADO) / factor,
        ease: "power1.in",
        immediateRender: false,
        onUpdate: () => pintar(progreso.n),
      },
    );
    // Al terminar de borrar se cambia al texto nuevo.
    tl.add(() => {
      letras = letrasNuevas;
      pintar(0);
    });
  }

  // Fase 2: se escribe el texto nuevo a velocidad constante.
  tl.fromTo(
    progreso,
    { n: 0 },
    {
      n: letrasNuevas.length,
      duration: letrasNuevas.length / velocidad,
      ease: "none",
      immediateRender: false,
      onUpdate: () => pintar(progreso.n),
    },
  );

  // Cursor parpadeando un momento, luego se retira la etiqueta y se deja el texto limpio.
  // CAMBIO: la pausa final y el desvanecimiento se dividen por la velocidad.
  tl.to({}, { duration: PAUSA_FINAL_S / factor });
  tl.to(etiqueta, { opacity: 0, duration: DESVANECER_S / factor });
  tl.add(() => {
    div.textContent = texto;
  });

  return tl;
}

// El borrador ya escrito pasa a definitivo: brillo + opacidad (CSS) y etiqueta del agente.
export function solidificar(o: OpcionesSolidificar): gsap.core.Timeline {
  const { div, etiqueta, marco, nombreAgente } = o;
  const velocidad = Math.max(0.1, o.velocidad);

  // Se reinicia la animación CSS quitando y volviendo a poner la clase.
  div.classList.remove("solidificando");
  void div.offsetWidth;
  div.style.setProperty("--dur-solidificar", `${DURACION_SOLIDIFICAR_S / velocidad}s`);
  div.classList.add("solidificando");

  // La etiqueta aparece sobre el inicio del campo.
  etiqueta.textContent = nombreAgente;
  const c = div.getBoundingClientRect();
  const m = marco.getBoundingClientRect();
  colocarEtiqueta(etiqueta, marco, c.left - m.left, c.top - m.top);

  const tl = gsap.timeline();
  tl.set(etiqueta, { opacity: 1 });
  tl.to({}, { duration: 0.8 / velocidad });
  // CAMBIO: el desvanecimiento también se divide por la velocidad.
  tl.to(etiqueta, { opacity: 0, duration: DESVANECER_S / velocidad });
  tl.add(() => div.classList.remove("solidificando"));
  return tl;
}