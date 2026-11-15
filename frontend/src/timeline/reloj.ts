// ---------------------------------------------------------------------------
// reloj.ts — Reloj inyectable para el reproductor.
// El reproductor nunca llama a setTimeout ni a performance.now directamente:
// recibe un `Reloj`. En producción es `relojReal`; en las pruebas es el reloj
// falso, cuyo tiempo avanza solo cuando la prueba lo ordena.
// ---------------------------------------------------------------------------

// Función que cancela una tarea programada (se puede llamar varias veces sin efecto extra).
export type Cancelar = () => void;

// Contrato mínimo de un reloj: leer el tiempo y programar un callback.
export interface Reloj {
  // Instante actual en milisegundos (solo sirve para medir diferencias).
  ahora(): number;
  // Ejecuta `callback` una vez, dentro de `ms` milisegundos; devuelve cómo cancelarlo.
  programar(ms: number, callback: () => void): Cancelar;
}

// Reloj de producción: performance.now() (monótono, inmune a cambios de hora del sistema) y setTimeout.
export const relojReal: Reloj = {
  ahora: () => performance.now(),
  programar: (ms, callback) => {
    const id = setTimeout(callback, ms);
    return () => clearTimeout(id);
  },
};

// Reloj de pruebas: añade control manual del tiempo y un contador de tareas pendientes.
export interface RelojFalso extends Reloj {
  // Avanza el tiempo `ms` milisegundos y dispara, en orden, todo lo que venza.
  avanzar(ms: number): void;
  // Cantidad de tareas programadas que todavía no corrieron ni se cancelaron.
  pendientes(): number;
}

// Una tarea programada en el reloj falso.
interface Tarea {
  readonly id: number;
  readonly vence: number;
  readonly callback: () => void;
}

// Crea un reloj falso que arranca en `inicioMs` (0 por defecto).
export function crearRelojFalso(inicioMs = 0): RelojFalso {
  let instante = inicioMs;
  let siguienteId = 1;
  let tareas: Tarea[] = [];

  // Elige la tarea que vence antes (con empate, la programada antes) sin pasarse de `limite`.
  function tomarSiguiente(limite: number): Tarea | null {
    let elegida: Tarea | null = null;
    for (const tarea of tareas) {
      // Las tareas que vencen después del límite no entran en este avance.
      if (tarea.vence > limite) continue;
      // Gana el menor vencimiento; si empatan, el menor id (el que se programó primero).
      if (
        elegida === null ||
        tarea.vence < elegida.vence ||
        (tarea.vence === elegida.vence && tarea.id < elegida.id)
      ) {
        elegida = tarea;
      }
    }
    return elegida;
  }

  return {
    ahora: () => instante,

    programar(ms, callback) {
      // Como setTimeout: una espera negativa o inválida se trata como 0.
      const espera = Number.isFinite(ms) ? Math.max(0, ms) : 0;
      const id = siguienteId++;
      tareas.push({ id, vence: instante + espera, callback });
      // Cancelar quita la tarea por id; si ya no está, no pasa nada.
      return () => {
        tareas = tareas.filter((t) => t.id !== id);
      };
    },

    avanzar(ms) {
      // `!(ms >= 0)` también atrapa NaN.
      if (!(ms >= 0)) {
        throw new RangeError(`avanzar necesita un número mayor o igual a 0; recibió ${String(ms)}.`);
      }
      const destino = instante + ms;
      let tarea = tomarSiguiente(destino);
      // Mientras haya tareas vencidas dentro del avance, se ejecutan una por una.
      while (tarea !== null) {
        const actual = tarea;
        tareas = tareas.filter((t) => t.id !== actual.id);
        // Dentro del callback, ahora() vale el instante de vencimiento de la tarea.
        instante = Math.max(instante, actual.vence);
        actual.callback();
        // El callback pudo programar o cancelar tareas: se vuelve a buscar la siguiente.
        tarea = tomarSiguiente(destino);
      }
      instante = destino;
    },

    pendientes: () => tareas.length,
  };
}