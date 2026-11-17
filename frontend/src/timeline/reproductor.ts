// ---------------------------------------------------------------------------
// reproductor.ts — Reproduce una secuencia de eventos sobre el reductor.
// Sin dependencias de React: expone obtener()/suscribir() para que el paso del
// lienzo lo envuelva con useSyncExternalStore. El tiempo viene de un `Reloj`
// inyectable. Calcula siempre contra reloj.ahora() (no acumula retardos), así que
// un setTimeout tardío aplica de golpe todo lo vencido y no se desfasa.
// ---------------------------------------------------------------------------
import { ordenar } from "./ordenador.ts";
import type { Problema } from "./ordenador.ts";
import { crearEstadoInicial, reducir, reducirTodos } from "./reducer.ts";
import { relojReal } from "./reloj.ts";
import type { Cancelar, Reloj } from "./reloj.ts";
import type { Estado, Evento } from "./types.ts";

// NUEVO: única fuente de verdad de las velocidades. La interfaz (App.tsx) y la
// validación de velocidad() leen esta lista; para añadir una velocidad se toca solo aquí.
export const VELOCIDADES = [1, 2, 3] as const;

// CAMBIO: el tipo se deriva de la lista (antes era `1 | 2` escrito a mano).
export type Velocidad = (typeof VELOCIDADES)[number];

// Tope por defecto de la espera entre dos eventos (ms de grabación).
export const MAX_ESPERA_POR_DEFECTO_MS = 3000;

// Margen para absorber errores de coma flotante al comparar instantes (ms).
const EPSILON_MS = 0.001;

// Opciones al crear el reproductor.
export interface OpcionesReproductor {
  // Reloj a usar; por defecto el real. Las pruebas inyectan el falso.
  readonly reloj?: Reloj;
  // Tope de espera entre eventos consecutivos; por defecto 3000 ms.
  readonly maxEsperaMs?: number;
}

// Foto inmutable del reproductor: lo que la interfaz necesita para dibujarse.
export interface VistaReproductor {
  readonly estado: Estado;
  // Cuántos eventos están aplicados (0..total); sirve como índice de seek.
  readonly aplicados: number;
  readonly total: number;
  readonly reproduciendo: boolean;
  readonly velocidad: Velocidad;
  // true cuando ya se aplicaron todos los eventos (y hay al menos uno).
  readonly terminado: boolean;
}

// Función que se llama cada vez que la vista cambia.
export type Oyente = (vista: VistaReproductor) => void;

// API pública del reproductor.
export interface Reproductor {
  // Vista actual (misma referencia mientras nada cambie).
  obtener(): VistaReproductor;
  // Registra un oyente; devuelve la función que lo da de baja.
  suscribir(oyente: Oyente): () => void;
  reproducir(): void;
  pausar(): void;
  // Vuelve al inicio y queda en pausa.
  reiniciar(): void;
  // CAMBIO: cambia la velocidad (cualquiera de VELOCIDADES); funciona también durante la reproducción.
  velocidad(valor: Velocidad): void;
  // Salta a un punto con `indice` eventos aplicados (0..total); RangeError si no es válido.
  irA(indice: number): void;
  // Cancela temporizadores y oyentes; el reproductor deja de responder.
  destruir(): void;
}

// Error de creación: la secuencia tiene problemas y no se puede reproducir.
export class ErrorSecuencia extends Error {
  readonly problemas: readonly Problema[];

  constructor(problemas: readonly Problema[]) {
    const resumen = problemas.map((p) => `- [${p.codigo}] ${p.detalle}`).join("\n");
    super(`La secuencia de eventos no se puede reproducir:\n${resumen}`);
    this.name = "ErrorSecuencia";
    this.problemas = problemas;
  }
}

// Calcula en qué instante (ms desde el inicio de la grabación) se aplica cada evento.
// Cada brecha entre eventos sale de los timestamps, recortada a [0, maxEsperaMs]:
// una brecha inválida o negativa no espera nada y una muy larga se acorta.
export function calcularInstantes(eventos: readonly Evento[], maxEsperaMs: number): number[] {
  const instantes: number[] = [];
  let acumulado = 0;
  let anterior: number | null = null;
  // Un ciclo por evento: acumula la brecha respecto al anterior.
  for (const evento of eventos) {
    const marca = Date.parse(evento.timestamp);
    // El primer evento siempre está en el instante 0.
    if (anterior !== null) {
      const brecha = marca - anterior;
      // Si alguna de las dos marcas es inválida, la resta da NaN y no se suma nada.
      if (Number.isFinite(brecha)) {
        acumulado += Math.min(Math.max(brecha, 0), maxEsperaMs);
      }
    }
    instantes.push(acumulado);
    anterior = marca;
  }
  return instantes;
}

// Crea un reproductor para una lista de eventos (se ordena y valida al crearlo).
export function crearReproductor(
  eventos: readonly Evento[],
  opciones: OpcionesReproductor = {},
): Reproductor {
  const reloj = opciones.reloj ?? relojReal;
  const maxEsperaMs = opciones.maxEsperaMs ?? MAX_ESPERA_POR_DEFECTO_MS;
  // `!(x >= 0)` también atrapa NaN.
  if (!(maxEsperaMs >= 0)) {
    throw new RangeError(`maxEsperaMs debe ser un número mayor o igual a 0; recibió ${String(maxEsperaMs)}.`);
  }

  // El reductor solo debe recibir secuencias limpias: se valida acá y no más adelante.
  const orden = ordenar(eventos);
  if (!orden.ok) throw new ErrorSecuencia(orden.problemas);
  const lista = orden.eventos;
  const total = lista.length;
  const instantes = calcularInstantes(lista, maxEsperaMs);

  // --- Estado interno ---
  let estado = crearEstadoInicial();
  let aplicadosCuenta = 0;
  let reproduciendo = false;
  let factor: Velocidad = 1;
  // Posición de la reproducción (ms de grabación) en el último ancla, y el reloj en ese momento.
  let posicionBase = 0;
  let anclaReloj = 0;
  let cancelarTemporizador: Cancelar | null = null;
  let destruido = false;
  const oyentes = new Set<Oyente>();

  // Arma la foto inmutable con el estado interno actual.
  function construirVista(): VistaReproductor {
    return {
      estado,
      aplicados: aplicadosCuenta,
      total,
      reproduciendo,
      velocidad: factor,
      terminado: total > 0 && aplicadosCuenta === total,
    };
  }

  let vista: VistaReproductor = construirVista();

  // Genera una vista nueva y avisa a los oyentes (una sola vez por acción).
  function publicar(): void {
    vista = construirVista();
    // Se itera sobre una copia: un oyente puede darse de baja mientras se notifica.
    for (const oyente of [...oyentes]) oyente(vista);
  }

  // Posición actual en ms de grabación: fija en pausa, avanza con el reloj al reproducir.
  function posicionActual(): number {
    if (!reproduciendo) return posicionBase;
    return posicionBase + (reloj.ahora() - anclaReloj) * factor;
  }

  // Fija un nuevo punto de referencia para calcular la posición.
  function anclar(posicion: number): void {
    posicionBase = posicion;
    anclaReloj = reloj.ahora();
  }

  // Cancela el temporizador pendiente, si lo hay.
  function detenerTemporizador(): void {
    if (cancelarTemporizador !== null) {
      cancelarTemporizador();
      cancelarTemporizador = null;
    }
  }

  // Aplica, en orden, todos los eventos cuyo instante ya llegó; devuelve true si aplicó alguno.
  function aplicarVencidos(posicion: number): boolean {
    let huboCambio = false;
    // Ciclo: sigue mientras queden eventos pendientes y su instante ya haya llegado.
    while (aplicadosCuenta < total) {
      const instante = instantes[aplicadosCuenta];
      const evento = lista[aplicadosCuenta];
      // Defensa: no debería pasar, pero evita un bucle infinito si faltara un dato.
      if (instante === undefined || evento === undefined) break;
      // Si el siguiente evento todavía no llegó, se termina.
      if (instante > posicion + EPSILON_MS) break;
      estado = reducir(estado, evento);
      aplicadosCuenta += 1;
      huboCambio = true;
    }
    return huboCambio;
  }

  // Si ya se aplicó todo, detiene la reproducción y deja la posición en el último evento.
  function cerrarSiTermino(): void {
    if (aplicadosCuenta >= total) {
      detenerTemporizador();
      posicionBase = total > 0 ? (instantes[total - 1] ?? 0) : 0;
      reproduciendo = false;
    }
  }

  // Programa el próximo evento a su instante (ajustado por la velocidad).
  function programarSiguiente(): void {
    detenerTemporizador();
    // En pausa o sin eventos pendientes no hay nada que programar.
    if (!reproduciendo || aplicadosCuenta >= total) return;
    const proximo = instantes[aplicadosCuenta];
    if (proximo === undefined) return;
    const espera = Math.max(0, (proximo - posicionActual()) / factor);
    cancelarTemporizador = reloj.programar(espera, alDisparar);
  }

  // Se ejecuta cuando vence el temporizador: aplica lo vencido y programa el siguiente.
  function alDisparar(): void {
    cancelarTemporizador = null;
    // Un disparo que llega después de pausar o destruir se ignora.
    if (destruido || !reproduciendo) return;
    const huboCambio = aplicarVencidos(posicionActual());
    cerrarSiTermino();
    programarSiguiente();
    // Si el temporizador llegó apenas antes de tiempo no hubo cambios y no se notifica.
    if (huboCambio) publicar();
  }

  // Deja todo como al principio: sin eventos aplicados, en pausa y en la posición 0.
  function volverAlInicio(): void {
    detenerTemporizador();
    estado = crearEstadoInicial();
    aplicadosCuenta = 0;
    posicionBase = 0;
    reproduciendo = false;
  }

  return {
    obtener: () => vista,

    suscribir(oyente) {
      // Un reproductor destruido ya no tiene oyentes.
      if (destruido) return () => {};
      oyentes.add(oyente);
      return () => {
        oyentes.delete(oyente);
      };
    },

    reproducir() {
      // Ya reproduciendo, destruido o sin eventos: no hay nada que hacer.
      if (destruido || reproduciendo || total === 0) return;
      // Si ya había terminado, reproducir vuelve a empezar desde el principio.
      if (aplicadosCuenta >= total) volverAlInicio();
      reproduciendo = true;
      anclar(posicionBase);
      // El evento del instante 0 (o los ya vencidos tras un seek) se aplican de inmediato.
      aplicarVencidos(posicionBase);
      cerrarSiTermino();
      programarSiguiente();
      publicar();
    },

    pausar() {
      if (destruido || !reproduciendo) return;
      const posicion = posicionActual();
      // Primero se aplica lo que ya estuviera vencido y aún no se hubiera procesado.
      aplicarVencidos(posicion);
      cerrarSiTermino();
      // Si no terminó, se congela la posición exacta donde se pausó.
      if (reproduciendo) {
        posicionBase = posicion;
        reproduciendo = false;
        detenerTemporizador();
      }
      publicar();
    },

    reiniciar() {
      if (destruido) return;
      volverAlInicio();
      publicar();
    },

    velocidad(valor) {
      // CAMBIO: solo se admiten las velocidades de VELOCIDADES (el mensaje sale de la misma lista).
      if (!VELOCIDADES.includes(valor)) {
        throw new RangeError(
          `La velocidad debe ser una de ${VELOCIDADES.join(", ")}; recibió ${String(valor)}.`,
        );
      }
      if (destruido || valor === factor) return;
      const posicion = posicionActual();
      // Si está reproduciendo, se aplica lo vencido y se re-ancla antes de cambiar el factor.
      if (reproduciendo) {
        aplicarVencidos(posicion);
        cerrarSiTermino();
      }
      // Si sigue reproduciendo (no terminó), la nueva referencia parte de la posición actual.
      if (reproduciendo) anclar(posicion);
      factor = valor;
      // En pausa programarSiguiente no hace nada; reproduciendo, recalcula la espera.
      programarSiguiente();
      publicar();
    },

    irA(indice) {
      // Un índice fuera de 0..total o no entero es un error de uso.
      if (!Number.isInteger(indice) || indice < 0 || indice > total) {
        throw new RangeError(`irA necesita un entero entre 0 y ${total}; recibió ${String(indice)}.`);
      }
      if (destruido) return;
      const seguiaReproduciendo = reproduciendo;
      detenerTemporizador();
      // El reductor es puro: reconstruir desde cero da exactamente el mismo estado.
      estado = reducirTodos(crearEstadoInicial(), lista.slice(0, indice));
      aplicadosCuenta = indice;
      // La posición queda en el instante del último evento aplicado.
      posicionBase = indice === 0 ? 0 : (instantes[indice - 1] ?? 0);
      reproduciendo = seguiaReproduciendo;
      // Si estaba reproduciendo, continúa desde el nuevo punto.
      if (reproduciendo) {
        anclar(posicionBase);
        aplicarVencidos(posicionBase);
        cerrarSiTermino();
        programarSiguiente();
      }
      publicar();
    },

    destruir() {
      destruido = true;
      detenerTemporizador();
      oyentes.clear();
      reproduciendo = false;
      // La vista final se actualiza sin avisar: ya no queda nadie escuchando.
      vista = construirVista();
    },
  };
}