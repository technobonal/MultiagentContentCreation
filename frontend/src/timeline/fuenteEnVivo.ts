// ---------------------------------------------------------------------------
// fuenteEnVivo.ts — Fuente de eventos por SSE con la misma interfaz que Reproductor.
// Sin React. Cada mensaje se valida con el contrato (validarEvento) y se guarda en un
// buffer contiguo por seq. El servidor marca el ritmo: mientras se reproduce, cada
// evento pasa por el reductor apenas llega; en pausa se acumula y se aplica de golpe
// al reanudar. Ante un hueco se cierra y se reconecta con ?desde=<último seq recibido>.
// Así Lienzo, MesaAgentes y useReproductor no cambian.
// Fallos del run: el evento nombrado `run_error` del servidor corta la conexión con un error
// visible (si no, el EventSource reconecta solo y el servidor reenvía el error sin fin). Como red
// de seguridad, varias reconexiones seguidas sin ningún evento nuevo también terminan en error.
// ---------------------------------------------------------------------------
import { resumirErrores, validarEvento } from "../lib/validar.ts";
import type { ResultadoValidacion } from "../lib/validar.ts";
import { crearEstadoInicial, reducir, reducirTodos } from "./reducer.ts";
import { VELOCIDADES } from "./reproductor.ts";
import type { Oyente, Reproductor, Velocidad, VistaReproductor } from "./reproductor.ts";
import type { Evento } from "./types.ts";

// Cuántos huecos seguidos se intentan resolver reconectando antes de mostrar un error.
export const MAX_REINTENTOS_HUECO = 3;

// Cuántas reconexiones seguidas, sin recibir ningún evento nuevo, se toleran antes de mostrar un error.
export const MAX_RECONEXIONES_SIN_PROGRESO = 5;

// Valor de readyState de EventSource cuando el navegador desistió de reconectar.
const ESTADO_CERRADO = 2;

// Estados posibles de la conexión, para mostrarlos en pantalla.
export type EstadoConexion = "conectando" | "abierta" | "reconectando" | "cerrada" | "error";

// Contrato mínimo de un EventSource (lo que usamos de él); permite inyectar uno falso en pruebas.
export interface FuenteSse {
  readonly readyState: number;
  addEventListener(tipo: string, oyente: (ev: MessageEvent) => void): void;
  close(): void;
}

// Función que abre una conexión SSE a una URL.
export type FabricaSse = (url: string) => FuenteSse;

// Fábrica de producción: el EventSource real del navegador.
export const fabricaReal: FabricaSse = (url) => new EventSource(url);

// Opciones al crear la fuente (ambas inyectables para las pruebas).
export interface OpcionesFuenteEnVivo {
  readonly fabrica?: FabricaSse;
  readonly validar?: (dato: unknown) => ResultadoValidacion;
}

// Foto inmutable de la conexión y del buffer, para mostrar estado y alimentar las miniaturas.
export interface VistaEnVivo {
  readonly conexion: EstadoConexion;
  // Todos los eventos recibidos y validados, contiguos desde el seq 1.
  readonly eventos: readonly Evento[];
  // Texto para el usuario (error o aviso); null si no hay nada que decir.
  readonly mensaje: string | null;
}

// Un Reproductor que además expone el estado de la conexión.
export interface FuenteEnVivo extends Reproductor {
  obtenerEnVivo(): VistaEnVivo;
}

// Arma la URL de la conexión: con ?desde=N solo si ya se recibió algo.
function construirUrl(base: string, desde: number): string {
  // Sin eventos previos se pide todo desde el principio.
  if (desde <= 0) return base;
  // Respeta una query ya existente en la URL base.
  return `${base}${base.includes("?") ? "&" : "?"}desde=${desde}`;
}

// Redacta el aviso a partir del evento nombrado `evento_invalido` que envía el servidor.
function describirRechazo(crudo: unknown): string {
  try {
    const info = JSON.parse(String(crudo)) as { seq?: unknown; tipo?: unknown; motivos?: unknown };
    // Los motivos vienen como lista de textos.
    const motivos = Array.isArray(info.motivos) ? info.motivos.map(String).join("; ") : "sin detalle";
    return `El servidor rechazó el evento seq ${String(info.seq)} (${String(info.tipo)}): ${motivos}`;
  } catch {
    return "El servidor rechazó un evento (sin detalle legible).";
  }
}

// Redacta el aviso a partir del evento nombrado `run_error` que envía el servidor cuando el run falla.
function describirRunError(crudo: unknown): string {
  try {
    const info = JSON.parse(String(crudo)) as { motivos?: unknown };
    // Los motivos vienen como lista de textos; si no hay, se avisa sin detalle.
    const motivos = Array.isArray(info.motivos) ? info.motivos.map(String).join("; ") : "sin detalle";
    return `La ejecución falló en el servidor: ${motivos}`;
  } catch {
    return "La ejecución falló en el servidor (sin detalle legible).";
  }
}

// Crea la fuente en vivo y conecta de inmediato. `urlBase` p. ej. "/api/runs/run_x/eventos".
export function crearFuenteEnVivo(
  urlBase: string,
  opciones: OpcionesFuenteEnVivo = {},
): FuenteEnVivo {
  const fabrica = opciones.fabrica ?? fabricaReal;
  const validar = opciones.validar ?? validarEvento;

  // --- Estado interno ---
  let buffer: readonly Evento[] = []; // eventos válidos y contiguos (se reemplaza, nunca se muta)
  let ultimoRecibido = 0; // seq del último evento guardado en el buffer
  let estado = crearEstadoInicial();
  let aplicados = 0; // cuántos eventos del buffer ya pasaron por el reductor
  let reproduciendo = true; // en vivo se arranca aplicando
  let factor: Velocidad = 1; // se guarda por la interfaz, pero el ritmo lo marca el servidor
  let flujoCompleto = false; // true cuando llegó run_finalizada
  let conexion: EstadoConexion = "conectando";
  let mensaje: string | null = null;
  let reintentosHueco = 0;
  let reconexionesSinProgreso = 0; // cortes seguidos sin que haya entrado ningún evento nuevo
  let destruido = false;
  let actual: FuenteSse | null = null;
  const oyentes = new Set<Oyente>();

  // true cuando el flujo terminó y todo está aplicado.
  function terminadoAhora(): boolean {
    return flujoCompleto && buffer.length > 0 && aplicados === buffer.length;
  }

  // Arma la vista de reproducción con el estado interno actual.
  function construirVista(): VistaReproductor {
    return {
      estado,
      aplicados,
      total: buffer.length,
      reproduciendo,
      velocidad: factor,
      terminado: terminadoAhora(),
    };
  }

  // Arma la vista de conexión con el estado interno actual.
  function construirEnVivo(): VistaEnVivo {
    return { conexion, eventos: buffer, mensaje };
  }

  let vista = construirVista();
  let vistaEnVivo = construirEnVivo();

  // Rehace solo las vistas que cambiaron (misma referencia = sin re-render) y avisa a los oyentes.
  function publicar(): void {
    let cambio = false;
    // La vista de reproducción cambia si algún dato propio cambió.
    if (
      vista.estado !== estado ||
      vista.aplicados !== aplicados ||
      vista.total !== buffer.length ||
      vista.reproduciendo !== reproduciendo ||
      vista.velocidad !== factor ||
      vista.terminado !== terminadoAhora()
    ) {
      vista = construirVista();
      cambio = true;
    }
    // La vista de conexión cambia con la conexión, el buffer o el mensaje.
    if (
      vistaEnVivo.conexion !== conexion ||
      vistaEnVivo.eventos !== buffer ||
      vistaEnVivo.mensaje !== mensaje
    ) {
      vistaEnVivo = construirEnVivo();
      cambio = true;
    }
    // Sin cambios no se molesta a nadie.
    if (!cambio) return;
    // Se itera sobre una copia: un oyente puede darse de baja mientras se notifica.
    for (const oyente of [...oyentes]) oyente(vista);
  }

  // Cierra la conexión vigente, si la hay.
  function cerrarActual(): void {
    if (actual !== null) {
      actual.close();
      actual = null;
    }
  }

  // Pasa por el reductor todos los eventos del buffer que aún no se aplicaron.
  function aplicarPendientes(): void {
    // Ciclo: avanza hasta alcanzar el final del buffer.
    while (aplicados < buffer.length) {
      const evento = buffer[aplicados];
      // Defensa por el acceso indexado; no debería ocurrir.
      if (evento === undefined) break;
      estado = reducir(estado, evento);
      aplicados += 1;
    }
  }

  // Si el flujo terminó y todo está aplicado, la reproducción se detiene sola.
  function cerrarSiTermino(): void {
    if (flujoCompleto && aplicados >= buffer.length) reproduciendo = false;
  }

  // Corta la conexión y deja un error visible (nunca se oculta un problema).
  function fallar(texto: string): void {
    cerrarActual();
    conexion = "error";
    mensaje = texto;
    publicar();
  }

  // Guarda un evento ya validado: idempotente, contiguo y con control de huecos.
  function recibirEvento(evento: Evento): void {
    // Idempotencia: un seq ya recibido (por ejemplo, tras reconectar) se ignora.
    if (evento.seq <= ultimoRecibido) return;

    const primero = buffer[0];
    // Una ejecución distinta no puede mezclarse con la que ya está en el buffer.
    if (primero !== undefined && evento.run_id !== primero.run_id) {
      fallar(`Llegó un evento del run ${evento.run_id}; esta conexión es del run ${primero.run_id}.`);
      return;
    }

    const esperado = ultimoRecibido + 1;
    // Hueco: no se guarda; se vuelve a pedir lo que falta desde el último seq recibido.
    if (evento.seq !== esperado) {
      reintentosHueco += 1;
      // Si el hueco persiste tras varios intentos, se muestra el error.
      if (reintentosHueco > MAX_REINTENTOS_HUECO) {
        fallar(`Hueco persistente: se esperaba el seq ${esperado} y llegó el ${evento.seq}.`);
        return;
      }
      conexion = "reconectando";
      mensaje = `Hueco: se esperaba el seq ${esperado} y llegó el ${evento.seq}; pidiendo de nuevo lo que falta.`;
      conectar(ultimoRecibido);
      publicar();
      return;
    }

    // Evento esperado: entra al buffer y el contador de huecos vuelve a cero.
    buffer = [...buffer, evento];
    ultimoRecibido = evento.seq;
    reintentosHueco = 0;
    reconexionesSinProgreso = 0; // entró un evento nuevo: hubo progreso

    // run_finalizada cierra el flujo: así el navegador no reconecta inútilmente.
    if (evento.tipo === "run_finalizada") {
      flujoCompleto = true;
      cerrarActual();
      conexion = "cerrada";
      mensaje = null;
    }
    // Mientras se reproduce, el evento se aplica apenas llega.
    if (reproduciendo) {
      aplicarPendientes();
      cerrarSiTermino();
    }
    publicar();
  }

  // Interpreta el texto de un mensaje SSE: JSON, contrato y recepción.
  function procesarMensaje(crudo: unknown): void {
    // Un mensaje sin texto no es un evento del contrato.
    if (typeof crudo !== "string") {
      fallar("El servidor envió un mensaje sin texto.");
      return;
    }
    let dato: unknown;
    try {
      dato = JSON.parse(crudo);
    } catch {
      fallar("El servidor envió un mensaje que no es JSON válido.");
      return;
    }
    const resultado = validar(dato);
    // El contrato exige validar en el borde: un evento inválido se muestra, nunca se ignora.
    if (!resultado.ok) {
      fallar(`Evento inválido recibido del servidor:\n${resumirErrores(resultado.errores)}`);
      return;
    }
    recibirEvento(dato as Evento);
  }

  // Abre una conexión nueva pidiendo los eventos con seq mayor que `desde`.
  function conectar(desde: number): void {
    cerrarActual();
    const fuente = fabrica(construirUrl(urlBase, desde));
    actual = fuente;
    // Los avisos de una conexión que ya no es la vigente se descartan.
    const vigente = (): boolean => !destruido && actual === fuente;

    fuente.addEventListener("open", () => {
      if (!vigente()) return;
      conexion = "abierta";
      mensaje = null;
      publicar();
    });

    fuente.addEventListener("message", (ev) => {
      if (!vigente()) return;
      procesarMensaje(ev.data);
    });

    // Mensaje nombrado del backend: un evento no pasó la validación en el servidor.
    fuente.addEventListener("evento_invalido", (ev) => {
      if (!vigente()) return;
      fallar(describirRechazo(ev.data));
    });

    // Mensaje nombrado del backend: el run falló. Se corta aquí; si no, el EventSource reconectaría
    // solo y el servidor volvería a enviar el mismo error indefinidamente.
    fuente.addEventListener("run_error", (ev) => {
      if (!vigente()) return;
      fallar(describirRunError(ev.data));
    });

    fuente.addEventListener("error", () => {
      if (!vigente()) return;
      // El navegador desistió (404, 400, 204...): no reconectará solo.
      if (fuente.readyState === ESTADO_CERRADO) {
        fallar("El servidor cerró la conexión antes de terminar la ejecución (¿existe el run_id?).");
        return;
      }
      // Red de seguridad: reconectar una y otra vez sin recibir nada nuevo no lleva a ningún lado.
      reconexionesSinProgreso += 1;
      if (reconexionesSinProgreso > MAX_RECONEXIONES_SIN_PROGRESO) {
        fallar(
          `Se perdió la conexión ${reconexionesSinProgreso} veces seguidas sin recibir eventos nuevos; se detiene el reintento.`,
        );
        return;
      }
      // Corte de red: EventSource reconecta solo y reenvía Last-Event-ID.
      conexion = "reconectando";
      mensaje = "Conexión interrumpida; reintentando…";
      publicar();
    });
  }

  // Vuelve a cero: vacía el buffer, reconecta desde el principio y reproduce.
  function reiniciarInterno(): void {
    cerrarActual();
    buffer = [];
    ultimoRecibido = 0;
    estado = crearEstadoInicial();
    aplicados = 0;
    flujoCompleto = false;
    reintentosHueco = 0;
    reconexionesSinProgreso = 0;
    reproduciendo = true;
    conexion = "conectando";
    mensaje = null;
    conectar(0);
  }

  // Conexión inicial.
  conectar(0);

  return {
    obtener: () => vista,
    obtenerEnVivo: () => vistaEnVivo,

    suscribir(oyente) {
      // Una fuente destruida ya no tiene oyentes.
      if (destruido) return () => {};
      oyentes.add(oyente);
      return () => {
        oyentes.delete(oyente);
      };
    },

    reproducir() {
      if (destruido) return;
      // Si ya terminó, reproducir vuelve a empezar (como el reproductor de grabaciones).
      if (terminadoAhora()) {
        reiniciarInterno();
        publicar();
        return;
      }
      reproduciendo = true;
      // Lo acumulado durante la pausa se aplica de golpe.
      aplicarPendientes();
      cerrarSiTermino();
      publicar();
    },

    pausar() {
      if (destruido || !reproduciendo) return;
      // En pausa los eventos siguen llegando al buffer, pero no se aplican.
      reproduciendo = false;
      publicar();
    },

    reiniciar() {
      if (destruido) return;
      reiniciarInterno();
      publicar();
    },

    velocidad(valor) {
      // Misma validación que el reproductor de grabaciones.
      if (!VELOCIDADES.includes(valor)) {
        throw new RangeError(
          `La velocidad debe ser una de ${VELOCIDADES.join(", ")}; recibió ${String(valor)}.`,
        );
      }
      if (destruido) return;
      // Sin efecto real: en modo servidor el ritmo lo marca el backend.
      factor = valor;
      publicar();
    },

    irA(indice) {
      // Un índice fuera de 0..total o no entero es un error de uso.
      if (!Number.isInteger(indice) || indice < 0 || indice > buffer.length) {
        throw new RangeError(
          `irA necesita un entero entre 0 y ${buffer.length}; recibió ${String(indice)}.`,
        );
      }
      if (destruido) return;
      // El reductor es puro: reconstruir desde cero da exactamente el mismo estado.
      estado = reducirTodos(crearEstadoInicial(), buffer.slice(0, indice));
      aplicados = indice;
      // Mirar el pasado pausa: si siguiera reproduciendo, saltaría de nuevo al final.
      if (indice < buffer.length) {
        reproduciendo = false;
      } else {
        cerrarSiTermino();
      }
      publicar();
    },

    destruir() {
      destruido = true;
      cerrarActual();
      oyentes.clear();
      reproduciendo = false;
      // Las vistas finales se actualizan sin avisar: ya no queda nadie escuchando.
      vista = construirVista();
      vistaEnVivo = construirEnVivo();
    },
  };
}