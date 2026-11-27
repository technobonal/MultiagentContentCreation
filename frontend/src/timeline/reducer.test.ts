// ---------------------------------------------------------------------------
// reducer.test.ts — Pruebas del reductor (Paso 1, escritas antes que el código).
// Usan una secuencia sintética que reproduce la historia de la "cifra inventada".
// Si existe la grabación real (contracts/recordings/b5_cifra_inventada.json),
// se corre además un bloque con ella; si no, ese bloque se omite.
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { calcularSello, crearEstadoInicial, reducir, reducirTodos } from "./reducer.ts";
import { TIPOS_EVENTO } from "./types.ts";
import type { Estado, Evento } from "./types.ts";

// --- Utilidades de prueba ----------------------------------------------------

// Borrador de evento: todo menos lo que asigna `secuenciar`.
interface Borrador {
  agente: string;
  tipo: string;
  payload: unknown;
  slide?: number;
  causa?: number;
  run_id?: string;
}

// Crea un borrador de evento de forma compacta.
function d(
  agente: string,
  tipo: string,
  payload: unknown,
  extra: { slide?: number; causa?: number } = {},
): Borrador {
  return { agente, tipo, payload, ...extra };
}

// Asigna seq 1..n, timestamps cada 2 s y el sobre común.
function secuenciar(borradores: readonly Borrador[], runId = "run_demo"): Evento[] {
  return borradores.map((b, i) => {
    const seq = i + 1;
    const segundos = String(2 * seq).padStart(2, "0").slice(-2);
    const minutos = String(Math.floor((2 * seq) / 60)).padStart(2, "0");
    return {
      version: "0.1",
      run_id: b.run_id ?? runId,
      seq,
      timestamp: `2026-11-13T12:${minutos}:${segundos}Z`,
      origen: "grabado",
      agente: b.agente,
      tipo: b.tipo,
      ...(b.slide !== undefined ? { slide: b.slide } : {}),
      ...(b.causa !== undefined ? { causa: b.causa } : {}),
      payload: b.payload,
    } as unknown as Evento;
  });
}

// Congela un objeto en profundidad: cualquier mutación lanza error en modo estricto.
function congelarProfundo<T>(valor: T): T {
  if (valor !== null && typeof valor === "object" && !Object.isFrozen(valor)) {
    Object.freeze(valor);
    // Recorre cada propiedad para congelar también lo anidado.
    for (const hijo of Object.values(valor as Record<string, unknown>)) {
      congelarProfundo(hijo);
    }
  }
  return valor;
}

// Payloads reutilizables.
const CITA = { fragmento: "El Daily Scrum dura 15 minutos.", inicio: 100, fin: 131 };
const SELLO_1_1 = { afirmaciones_respaldadas: 1, afirmaciones_totales: 1 };

// Secuencia sintética completa (19 eventos). Slide 3: cifra inventada y su corrección.
const BORRADORES: Borrador[] = [
  /* 1 */ d("sistema", "run_iniciada", {
    entrada_ref: "entrada.json",
    plataforma: "instagram",
    idioma_salida: "es",
    num_slides: 6,
    verificacion: "verificada",
    fuente: { tipo: "documento", atribucion: "Scrum Guide 2020", licencia: "CC BY-SA 4.0" },
  }),
  /* 2 */ d("sistema", "fuente_indexada", { num_fragmentos: 12, num_caracteres: 9000, sha256: "a".repeat(64) }),
  /* 3 */ d("estratega", "brief_emitido", {
    angulo: "Scrum en pocas palabras",
    tono: "claro",
    num_slides: 6,
    tipo_mensaje: "lista_de_pasos",
    roles: ["gancho", "segundo_gancho", "desarrollo", "desarrollo", "cierre", "fuentes"],
  }),
  /* 4 */ d("director_arte", "plantilla_elegida", {
    plantilla_id: "lista_pasos_basica",
    modo: "auto",
    motivo: "Encaja con una lista de pasos.",
    confianza: 0.9,
  }),
  /* 5 */ d("director_arte", "colocar_fondo", { fondo: { tipo: "color", valor: "#112233" } }, { slide: 1 }),
  /* 6 */ d("director_arte", "escribir_texto", { campo: "titulo", texto: "Scrum en pocas palabras" }, { slide: 1 }),
  /* 7 */ d("redactor", "texto_propuesto", { campo: "cuerpo", texto: "La Daily dura 30 minutos" }, { slide: 3 }),
  /* 8 */ d("director_arte", "escribir_texto", { campo: "cuerpo", texto: "La Daily dura 30 minutos" }, { slide: 3 }),
  /* 9 */ d("revisor", "verificacion_fidelidad", {
    afirmacion_id: "a1",
    afirmacion: "La Daily dura 30 minutos",
    clasificacion: "factual",
    veredicto: "contradice",
    cita: CITA,
    motivo: "La fuente dice 15 minutos.",
  }, { slide: 3 }),
  /* 10 */ d("revisor", "hallazgo_abierto", {
    hallazgo_id: "h1",
    dimension: "fidelidad",
    gravedad: "bloqueante",
    evidencia: "La fuente dice 15 minutos.",
    explicacion: "La cifra no coincide con la fuente.",
    accion: "Reescribir con 15 minutos.",
    responsable: "redactor",
  }, { slide: 3 }),
  /* 11 */ d("redactor", "texto_propuesto", { campo: "cuerpo", texto: "La Daily dura como máximo 15 minutos" }, { slide: 3, causa: 10 }),
  /* 12 */ d("redactor", "corregir", {
    motivo: "Corrige la cifra.",
    operacion_nueva: { tipo: "escribir_texto", campo: "cuerpo", texto: "La Daily dura como máximo 15 minutos" },
  }, { slide: 3, causa: 8 }),
  /* 13 */ d("revisor", "verificacion_fidelidad", {
    afirmacion_id: "a1",
    afirmacion: "La Daily dura como máximo 15 minutos",
    clasificacion: "factual",
    veredicto: "respaldada",
    cita: CITA,
    motivo: "Coincide con la fuente.",
  }, { slide: 3 }),
  /* 14 */ d("revisor", "hallazgo_corregido", {
    hallazgo_id: "h1",
    resultado: "corregido",
    reevaluacion: "La cifra ya coincide.",
  }, { slide: 3, causa: 10 }),
  /* 15 */ d("revisor", "verificacion_fidelidad", {
    afirmacion_id: "a2",
    afirmacion: "Empieza hoy",
    clasificacion: "opinion_cta",
    veredicto: "no_aplica",
    cita: null,
    motivo: "Llamada a la acción.",
  }, { slide: 5 }),
  /* 16 */ d("sistema", "aprobacion_solicitada", {
    estado_revision: "aprobada",
    hallazgos_abiertos: 0,
    sello: SELLO_1_1,
  }),
  /* 17 */ d("humano", "editada", {
    campo: "titulo",
    texto_antes: "Scrum en pocas palabras",
    texto_despues: "Scrum, explicado simple",
  }, { slide: 1 }),
  /* 18 */ d("humano", "aprobada", { decision: "aprobada" }),
  /* 19 */ d("sistema", "run_finalizada", {
    estado_final: "aprobada",
    fact_ledger_ref: "ledger_demo",
    sello: SELLO_1_1,
  }),
];
const SECUENCIA = secuenciar(BORRADORES);

// --- Secuencia completa ------------------------------------------------------
describe("reductor: secuencia completa", () => {
  const final = reducirTodos(crearEstadoInicial(), SECUENCIA);

  it("llega al último seq sin anomalías ni hueco", () => {
    expect(final.ultimoSeq).toBe(19);
    expect(final.hueco).toBeNull();
    expect(final.anomalias).toEqual([]);
  });

  it("dibuja la corrección en el slide 3 y el título editado en el slide 1", () => {
    expect(final.lienzo.textos[3]?.cuerpo).toBe("La Daily dura como máximo 15 minutos");
    expect(final.lienzo.textos[1]?.titulo).toBe("Scrum, explicado simple");
    expect(final.lienzo.fondos[1]).toEqual({ tipo: "color", valor: "#112233" });
  });

  it("deja el hallazgo h1 corregido y el sello 1/1", () => {
    expect(final.hallazgos.h1?.estado).toBe("corregido");
    expect(calcularSello(final.ledger)).toEqual(SELLO_1_1);
  });

  it("registra origen grabado, agentes vistos, slide activo y la edición humana", () => {
    expect(final.origenes).toEqual(["grabado"]);
    expect(Object.keys(final.agentes).sort()).toEqual(
      ["director_arte", "estratega", "humano", "redactor", "revisor", "sistema"],
    );
    expect(final.slideActivo).toBe(1); // el último evento con slide es la edición del slide 1
    expect(final.ediciones).toHaveLength(1);
    expect(final.decision?.seq).toBe(18);
    expect(final.final?.estado_final).toBe("aprobada");
  });

  it("mantiene las dos capas separadas: la propuesta no es lo dibujado hasta corregir", () => {
    const hasta11 = reducirTodos(crearEstadoInicial(), SECUENCIA.slice(0, 11));
    expect(hasta11.propuestas[3]?.cuerpo).toBe("La Daily dura como máximo 15 minutos");
    expect(hasta11.lienzo.textos[3]?.cuerpo).toBe("La Daily dura 30 minutos"); // aún sin corregir
  });
});

// --- Idempotencia ------------------------------------------------------------
describe("reductor: idempotencia", () => {
  it("un seq viejo devuelve el mismo objeto (===)", () => {
    const estado = reducirTodos(crearEstadoInicial(), SECUENCIA.slice(0, 5));
    const evento = SECUENCIA[2] as Evento;
    expect(reducir(estado, evento)).toBe(estado);
    expect(reducir(estado, SECUENCIA[4] as Evento)).toBe(estado); // el último aplicado
  });

  it("aplicar la secuencia dos veces seguidas da el mismo final", () => {
    const una = reducirTodos(crearEstadoInicial(), SECUENCIA);
    const dos = reducirTodos(una, SECUENCIA);
    expect(dos).toBe(una);
  });
});

// --- Huecos ------------------------------------------------------------------
describe("reductor: huecos", () => {
  it("con 1, 2 y 5 no avanza y marca hueco {3, 5}; al llegar el 3 se limpia", () => {
    const s2 = reducirTodos(crearEstadoInicial(), SECUENCIA.slice(0, 2));
    const conHueco = reducir(s2, SECUENCIA[4] as Evento);
    expect(conHueco.ultimoSeq).toBe(2);
    expect(conHueco.hueco).toEqual({ esperado: 3, recibido: 5 });
    expect(conHueco.brief).toBeNull(); // el evento 5 no se aplicó

    const s3 = reducir(conHueco, SECUENCIA[2] as Evento);
    expect(s3.ultimoSeq).toBe(3);
    expect(s3.hueco).toBeNull();
  });

  it("repetir el mismo salto no crea un objeto nuevo", () => {
    const s2 = reducirTodos(crearEstadoInicial(), SECUENCIA.slice(0, 2));
    const conHueco = reducir(s2, SECUENCIA[4] as Evento);
    expect(reducir(conHueco, SECUENCIA[4] as Evento)).toBe(conHueco);
  });

  it("si el primer evento no es el seq 1, marca hueco {1, n}", () => {
    const estado = reducir(crearEstadoInicial(), SECUENCIA[3] as Evento);
    expect(estado.ultimoSeq).toBe(0);
    expect(estado.hueco).toEqual({ esperado: 1, recibido: 4 });
  });
});

// --- Reanudación -------------------------------------------------------------
describe("reductor: reanudación", () => {
  it("estado hasta el 10 y luego eventos 8..19 (solapados) = flujo continuo", () => {
    const continuo = reducirTodos(crearEstadoInicial(), SECUENCIA);
    const hasta10 = reducirTodos(crearEstadoInicial(), SECUENCIA.slice(0, 10));
    const reanudado = reducirTodos(hasta10, SECUENCIA.slice(7)); // seq 8..19
    expect(reanudado).toEqual(continuo);
  });
});

// --- Inmutabilidad -----------------------------------------------------------
describe("reductor: inmutabilidad", () => {
  it("no muta entradas congeladas en profundidad", () => {
    let estado = congelarProfundo(crearEstadoInicial());
    // Congela cada evento y cada estado intermedio: cualquier mutación lanzaría.
    for (const evento of SECUENCIA) {
      estado = congelarProfundo(reducir(estado, congelarProfundo(evento)));
    }
    expect(estado.ultimoSeq).toBe(19);
  });

  it("comparte estructura: lo que no cambia conserva la misma referencia", () => {
    const antes = reducirTodos(crearEstadoInicial(), SECUENCIA.slice(0, 8));
    const despues = reducir(antes, SECUENCIA[8] as Evento); // verificacion_fidelidad
    expect(despues.lienzo).toBe(antes.lienzo);
    expect(despues.propuestas).toBe(antes.propuestas);
    expect(despues.ledger).not.toBe(antes.ledger);
  });
});

// --- Tabla por tipo (los 18 tipos) -------------------------------------------
interface CasoTipo {
  tipo: string;
  eventos: Borrador[];
  verificar: (e: Estado) => void;
}

// Toma el borrador de un seq de la secuencia sintética (1-indexado).
const b = (seq: number): Borrador => BORRADORES[seq - 1] as Borrador;
const IMAGEN = { campo: "imagen_producto", referencia: "foto-2", licencia: "Uso autorizado", texto_alternativo: "Un edificio" };

const CASOS: CasoTipo[] = [
  { tipo: "run_iniciada", eventos: [b(1)], verificar: (e) => expect(e.run?.fuente.licencia).toBe("CC BY-SA 4.0") },
  { tipo: "fuente_indexada", eventos: [b(2)], verificar: (e) => expect(e.fuente?.num_fragmentos).toBe(12) },
  { tipo: "brief_emitido", eventos: [b(3)], verificar: (e) => expect(e.brief?.num_slides).toBe(6) },
  { tipo: "plantilla_elegida", eventos: [b(4)], verificar: (e) => expect(e.plantilla?.plantilla_id).toBe("lista_pasos_basica") },
  { tipo: "texto_propuesto", eventos: [b(7)], verificar: (e) => {
    expect(e.propuestas[3]?.cuerpo).toBe("La Daily dura 30 minutos");
    expect(e.lienzo.textos[3]).toBeUndefined(); // no se dibuja
  } },
  { tipo: "colocar_fondo", eventos: [b(5)], verificar: (e) => expect(e.lienzo.fondos[1]).toEqual({ tipo: "color", valor: "#112233" }) },
  { tipo: "colocar_imagen", eventos: [d("director_arte", "colocar_imagen", IMAGEN, { slide: 2 })], verificar: (e) => {
    expect(e.lienzo.imagenes[2]?.imagen_producto).toEqual({ referencia: "foto-2", licencia: "Uso autorizado", texto_alternativo: "Un edificio" });
    expect(e.lienzo.fondos[2]).toBeUndefined(); // una imagen en su campo no es el fondo del slide
  } },
  { tipo: "escribir_texto", eventos: [b(6)], verificar: (e) => expect(e.lienzo.textos[1]?.titulo).toBe("Scrum en pocas palabras") },
  { tipo: "verificacion_fidelidad", eventos: [b(9)], verificar: (e) => expect(e.ledger.a1?.actual.veredicto).toBe("contradice") },
  { tipo: "hallazgo_abierto", eventos: [b(10)], verificar: (e) => {
    expect(e.hallazgos.h1?.estado).toBe("abierto");
    expect(e.hallazgos.h1?.gravedad).toBe("bloqueante");
  } },
  { tipo: "hallazgo_corregido", eventos: [b(10), b(14)], verificar: (e) => expect(e.hallazgos.h1?.estado).toBe("corregido") },
  { tipo: "corregir", eventos: [b(8), b(12)], verificar: (e) => expect(e.lienzo.textos[3]?.cuerpo).toBe("La Daily dura como máximo 15 minutos") },
  { tipo: "aprobacion_solicitada", eventos: [b(16)], verificar: (e) => {
    expect(e.revision?.estado_revision).toBe("aprobada");
    // Sin verificaciones previas el sello calculado es 0/0, distinto del 1/1 del evento.
    expect(e.anomalias.map((a) => a.codigo)).toContain("sello_distinto");
  } },
  { tipo: "aprobada", eventos: [b(18)], verificar: (e) => expect(e.decision?.seq).toBe(1) },
  { tipo: "asesoria", eventos: [b(6), d("asesor", "asesoria", { modelo: "m", frases_revisadas: 2, frases_totales: 2, alertas: [{ slide: 1, frase: "x", explicacion: "y", sugerencia: "reescribir" }] })],
    verificar: (e) => {
      expect(e.lienzo.textos[1]?.titulo).toBe("Scrum en pocas palabras"); // un consejo no toca el lienzo
      expect(e.decision).toBeNull();
      // La asesoría queda guardada con sus alertas para mostrarlas por slide.
      expect(e.asesor?.frases_revisadas).toBe(2);
      expect(e.asesor?.alertas[0]?.slide).toBe(1);
    } },
  { tipo: "rechazada", eventos: [d("humano", "rechazada", { decision: "rechazada", motivo: "No es lo que dice la fuente", responsable: "revisor" }, { slide: 3 })],
    verificar: (e) => {
      expect(e.decision?.rechazo).toEqual({ decision: "rechazada", motivo: "No es lo que dice la fuente", responsable: "revisor", slide: 3 });
    } },
  { tipo: "editada", eventos: [b(6), b(17)], verificar: (e) => {
    expect(e.lienzo.textos[1]?.titulo).toBe("Scrum, explicado simple");
    expect(e.ediciones).toHaveLength(1);
  } },
  { tipo: "run_finalizada", eventos: [b(19)], verificar: (e) => expect(e.final?.estado_final).toBe("aprobada") },
];

describe("reductor: un caso mínimo por tipo", () => {
  it("la tabla cubre exactamente los 18 tipos del catálogo", () => {
    expect(CASOS.map((c) => c.tipo).sort()).toEqual([...TIPOS_EVENTO].sort());
  });

  it.each(CASOS)("$tipo", ({ eventos, verificar, tipo }) => {
    const estado = reducirTodos(crearEstadoInicial(), secuenciar(eventos));
    // El último evento aplicado es del tipo probado.
    expect(estado.ultimoSeq).toBe(eventos.length);
    expect(estado.agentes[eventos[eventos.length - 1]?.agente ?? ""]?.tipo).toBe(tipo);
    verificar(estado);
  });
});

// --- Ledger ------------------------------------------------------------------
describe("reductor: ledger de fidelidad", () => {
  it("a1 pasa de contradice a respaldada con 2 entradas de historial", () => {
    const final = reducirTodos(crearEstadoInicial(), SECUENCIA);
    const a1 = final.ledger.a1;
    expect(a1?.actual.veredicto).toBe("respaldada");
    expect(a1?.historial.map((h) => h.veredicto)).toEqual(["contradice", "respaldada"]);
    expect(a1?.actual.afirmacion).toBe("La Daily dura como máximo 15 minutos");
  });

  it("el sello calculado coincide con el del evento y excluye opinion_cta", () => {
    const final = reducirTodos(crearEstadoInicial(), SECUENCIA);
    expect(calcularSello(final.ledger)).toEqual(final.revision?.sello);
    expect(final.ledger.a2?.actual.clasificacion).toBe("opinion_cta");
  });

  it("no_verificada cuenta en el total pero no como respaldada", () => {
    const eventos = secuenciar([
      d("revisor", "verificacion_fidelidad", {
        afirmacion_id: "a1", afirmacion: "x", clasificacion: "factual",
        veredicto: "no_verificada", cita: null, motivo: "Cita no literal.",
      }, { slide: 2 }),
    ]);
    const estado = reducirTodos(crearEstadoInicial(), eventos);
    expect(calcularSello(estado.ledger)).toEqual({ afirmaciones_respaldadas: 0, afirmaciones_totales: 1 });
  });
});

// --- Hallazgos: "persiste" ---------------------------------------------------
describe("reductor: hallazgo_corregido con resultado persiste", () => {
  it("mantiene el hallazgo abierto y guarda la reevaluación", () => {
    const eventos = secuenciar([
      b(10),
      d("revisor", "hallazgo_corregido", {
        hallazgo_id: "h1", resultado: "persiste", reevaluacion: "Sigue mal.",
      }, { slide: 3, causa: 1 }),
    ]);
    const estado = reducirTodos(crearEstadoInicial(), eventos);
    expect(estado.hallazgos.h1?.estado).toBe("abierto");
    expect(estado.hallazgos.h1?.reevaluaciones).toHaveLength(1);
    expect(estado.anomalias).toEqual([]);
  });
});

// --- Anomalías ---------------------------------------------------------------
describe("reductor: anomalías", () => {
  const codigos = (e: Estado): string[] => e.anomalias.map((a) => a.codigo);

  it("editada con texto_antes erróneo", () => {
    const eventos = secuenciar([
      b(6),
      d("humano", "editada", { campo: "titulo", texto_antes: "OTRO", texto_despues: "Nuevo" }, { slide: 1 }),
    ]);
    const estado = reducirTodos(crearEstadoInicial(), eventos);
    expect(codigos(estado)).toEqual(["editada_texto_antes_distinto"]);
    expect(estado.anomalias[0]?.seq).toBe(2);
    expect(estado.lienzo.textos[1]?.titulo).toBe("Nuevo"); // igual se aplica
  });

  it("editada sin cambio (antes = después)", () => {
    const eventos = secuenciar([
      b(6),
      d("humano", "editada", { campo: "titulo", texto_antes: "Scrum en pocas palabras", texto_despues: "Scrum en pocas palabras" }, { slide: 1 }),
    ]);
    expect(codigos(reducirTodos(crearEstadoInicial(), eventos))).toEqual(["editada_sin_cambio"]);
  });

  it("otro run_id se ignora y no avanza el seq", () => {
    const estado = reducirTodos(crearEstadoInicial(), SECUENCIA.slice(0, 3));
    const ajeno = secuenciar([b(1), b(1), b(1), b(1)], "run_otro")[3] as Evento; // seq 4 de otro run
    const resultado = reducir(estado, ajeno);
    expect(resultado.ultimoSeq).toBe(3);
    expect(codigos(resultado)).toEqual(["run_distinto"]);
  });

  it("tipo desconocido avanza el seq y se registra", () => {
    const eventos = secuenciar([b(1), d("sistema", "evento_nuevo", {})]);
    const estado = reducirTodos(crearEstadoInicial(), eventos);
    expect(estado.ultimoSeq).toBe(2);
    expect(codigos(estado)).toEqual(["tipo_desconocido"]);
  });

  it("hallazgo_corregido sin hallazgo previo", () => {
    const eventos = secuenciar([b(14)]);
    expect(codigos(reducirTodos(crearEstadoInicial(), eventos))).toEqual(["hallazgo_corregido_sin_hallazgo"]);
  });

  it("sello del evento distinto del calculado", () => {
    const eventos = secuenciar([
      d("sistema", "aprobacion_solicitada", {
        estado_revision: "aprobada_con_advertencias", hallazgos_abiertos: 0,
        sello: { afirmaciones_respaldadas: 3, afirmaciones_totales: 3 },
      }),
    ]);
    expect(codigos(reducirTodos(crearEstadoInicial(), eventos))).toEqual(["sello_distinto"]);
  });

  it("hallazgos_abiertos distinto del conteo real", () => {
    const eventos = secuenciar([
      b(10),
      d("sistema", "aprobacion_solicitada", {
        estado_revision: "requiere_humano", hallazgos_abiertos: 0,
        sello: { afirmaciones_respaldadas: 0, afirmaciones_totales: 0 },
      }),
    ]);
    expect(codigos(reducirTodos(crearEstadoInicial(), eventos))).toEqual(["hallazgos_abiertos_distinto"]);
  });

  it("aprobada con un bloqueante abierto", () => {
    const eventos = secuenciar([
      b(10),
      d("sistema", "aprobacion_solicitada", {
        estado_revision: "aprobada", hallazgos_abiertos: 1,
        sello: { afirmaciones_respaldadas: 0, afirmaciones_totales: 0 },
      }),
    ]);
    expect(codigos(reducirTodos(crearEstadoInicial(), eventos))).toEqual(["aprobada_con_bloqueante_abierto"]);
  });

  it("fondo de imagen sin licencia (defensa)", () => {
    const eventos = secuenciar([
      d("director_arte", "colocar_fondo", { fondo: { tipo: "imagen", referencia: "img_1", licencia: "" } }, { slide: 2 }),
    ]);
    expect(codigos(reducirTodos(crearEstadoInicial(), eventos))).toEqual(["fondo_imagen_sin_licencia"]);
  });

  it("colocar_imagen sin slide es una anomalía y dos imágenes del mismo slide conviven", () => {
    expect(codigos(reducirTodos(crearEstadoInicial(), secuenciar([d("director_arte", "colocar_imagen", IMAGEN)])))).toEqual(["slide_ausente"]);
    const estado = reducirTodos(crearEstadoInicial(), secuenciar([
      d("director_arte", "colocar_imagen", IMAGEN, { slide: 2 }),
      d("director_arte", "colocar_imagen", { ...IMAGEN, campo: "imagen_2", referencia: "foto-3" }, { slide: 2 }),
    ]));
    expect(Object.keys(estado.lienzo.imagenes[2] ?? {}).sort()).toEqual(["imagen_2", "imagen_producto"]);
  });

  it("fondo de imagen con licencia se guarda completo", () => {
    const fondo = { tipo: "imagen", referencia: "img_1", licencia: "CC0" };
    const estado = reducirTodos(
      crearEstadoInicial(),
      secuenciar([d("director_arte", "colocar_fondo", { fondo }, { slide: 2 })]),
    );
    expect(estado.lienzo.fondos[2]).toEqual(fondo);
    expect(estado.anomalias).toEqual([]);
  });

  it("evento que requiere slide pero no lo trae", () => {
    const eventos = secuenciar([d("director_arte", "escribir_texto", { campo: "titulo", texto: "x" })]);
    const estado = reducirTodos(crearEstadoInicial(), eventos);
    expect(codigos(estado)).toEqual(["slide_ausente"]);
    expect(estado.ultimoSeq).toBe(1);
  });
});

// --- Sincronía con el contrato -----------------------------------------------
// Si el repo está disponible, compara TIPOS_EVENTO con el enum de envelope.schema.json.
const esquemas = import.meta.glob("../../../contracts/events/envelope.schema.json", {
  eager: true,
  import: "default",
}) as Record<string, { properties: { tipo: { enum: string[] } } }>;
const envelope = Object.values(esquemas)[0];

describe.skipIf(!envelope)("sincronía con el contrato", () => {
  it("TIPOS_EVENTO coincide con el enum de envelope.schema.json", () => {
    expect([...TIPOS_EVENTO].sort()).toEqual([...(envelope?.properties.tipo.enum ?? [])].sort());
  });
});

// --- Grabación real (opcional) -----------------------------------------------
const grabaciones = import.meta.glob("../../../contracts/recordings/*.json", {
  eager: true,
  import: "default",
}) as Record<string, { eventos?: Evento[] }>;
const rutaReal = Object.keys(grabaciones).find((r) => r.includes("b5_cifra_inventada"));
const real = rutaReal ? grabaciones[rutaReal]?.eventos : undefined;

describe.skipIf(!real)("grabación real b5_cifra_inventada", () => {
  it("todos sus eventos dan seq = total, h1 corregido, sello 2/2 y cero anomalías", () => {
    const eventos = real ?? [];
    // El total sale de la propia grabación (validar.test.ts fija cuántos son).
    const total = eventos.length;
    const final = reducirTodos(crearEstadoInicial(), eventos);
    expect(total).toBeGreaterThan(0);
    expect(final.ultimoSeq).toBe(total);
    expect(final.hueco).toBeNull();
    expect(final.anomalias).toEqual([]);
    expect(final.hallazgos.h1?.estado).toBe("corregido");
    expect(calcularSello(final.ledger)).toEqual({ afirmaciones_respaldadas: 2, afirmaciones_totales: 2 });
    expect(final.lienzo.textos[3]?.cuerpo).toContain("como máximo 15 minutos");
  });
});
