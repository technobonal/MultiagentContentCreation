"""Pruebas de app/events/emisor.py: formato SSE, filtro de reanudación, espaciado y los dos flujos.

Cómo están hechas:
  - Las pruebas son síncronas y envuelven su escenario en asyncio.run (igual que test_canal_sse.py),
    así no hace falta pytest-asyncio. Cada prueba usa UN solo asyncio.run, porque la Condition de
    una Ejecucion queda atada al bucle donde se usa por primera vez.
  - `dormir` se inyecta con un reloj falso y todo lector de flujo_vivo lleva un tope de tiempo:
    ninguna prueba espera de verdad ni puede colgarse.
  - Las unitarias reemplazan el validador por uno controlado (acepta todo o rechaza lo que se pida);
    las que llevan "real" en el nombre usan la plantilla, el kit y el validador reales.
"""

import asyncio
import inspect
import json

import pytest

from app import config
from app.events import emisor
from app.events.emisor import (
    LATIDO_SSE,
    _espera_entre,
    filtrar_desde,
    flujo_sse,
    flujo_vivo,
    formatear_sse,
)
from app.events.validador import comprobar_evento
from app.resolution import cargar_fichas, resolver
from app.runs import registro as modulo_registro
from app.runs.orquestador import ejecutar_run
from app.runs.registro import Ejecucion, EstadoRun, EventoInvalido

RUN_ID = "run_prueba01"


# --------------------------------------------------------------------------------------
# Ayudas y fixtures
# --------------------------------------------------------------------------------------

def parsear_sse(texto: str) -> list[dict]:
    """Convierte el texto SSE en mensajes {id, event, data}; los latidos (comentarios) se ignoran."""
    mensajes = []
    for bloque in texto.split("\n\n"):  # los mensajes se separan por línea en blanco
        # El final del texto deja un bloque vacío y los latidos empiezan por ":": no son mensajes.
        if not bloque.strip() or bloque.startswith(":"):
            continue
        msg = {"id": None, "event": "message", "data": None}
        for linea in bloque.split("\n"):  # cada línea es "campo: valor"
            campo, _, valor = linea.partition(": ")
            if campo == "id":
                msg["id"] = int(valor)
            elif campo == "event":
                msg["event"] = valor
            elif campo == "data":
                msg["data"] = json.loads(valor)
        mensajes.append(msg)
    return mensajes


def hacer_evento(seq: int, segundos: int = 0) -> dict:
    """Evento mínimo con seq, tipo y timestamp; `segundos` lo separa del instante base (20:00:00)."""
    return {
        "seq": seq,
        "tipo": "run_iniciada",
        "timestamp": f"2026-11-11T20:00:{segundos:02d}-03:00",
        "payload": {"n": seq},
    }


def hacer_ejecucion() -> Ejecucion:
    """Ejecución real de prueba (debe crearse dentro del bucle de asyncio)."""
    return Ejecucion(RUN_ID, {"entrada": "x"}, None, "real")


async def juntar(generador) -> list[str]:
    """Consume un generador asíncrono completo y devuelve todos sus mensajes, en orden."""
    return [mensaje async for mensaje in generador]  # junta cada mensaje emitido


async def leer(ejecucion: Ejecucion, desde_seq: int = 0, latido: float = 0.05, limite: float = 2.0) -> list[str]:
    """Lee flujo_vivo hasta que termina; si se cuelga, falla a los `limite` segundos en vez de bloquear."""
    return await asyncio.wait_for(juntar(flujo_vivo(ejecucion, desde_seq, latido)), limite)


async def llenar(ejecucion: Ejecucion, cantidad: int) -> None:
    """Emite `cantidad` eventos válidos en la ejecución (seq 1..cantidad)."""
    for _ in range(cantidad):  # un evento por vuelta
        await ejecucion.emitir("sistema", "run_iniciada", {})


def reloj_falso() -> tuple[list[float], object]:
    """Devuelve (esperas, dormir): `dormir` anota la espera pedida en vez de dormir de verdad."""
    esperas: list[float] = []

    async def dormir(segundos: float) -> None:
        """Registra la espera pedida."""
        esperas.append(segundos)

    return esperas, dormir


@pytest.fixture
def contrato_ok(monkeypatch):
    """Validador que acepta todo evento, tanto en el emisor como al emitir en la Ejecucion."""
    monkeypatch.setattr(emisor, "comprobar_evento", lambda evento: [])
    monkeypatch.setattr(modulo_registro, "comprobar_evento", lambda evento: [])


# --------------------------------------------------------------------------------------
# formatear_sse
# --------------------------------------------------------------------------------------

def test_formatear_sse_con_id_y_nombre_arma_los_tres_campos():
    """Un mensaje con id y nombre lleva id, event y data, en ese orden, y termina en línea en blanco."""
    assert formatear_sse({"a": 1}, id_evento=4, nombre="evento_invalido") == (
        'id: 4\nevent: evento_invalido\ndata: {"a":1}\n\n'
    )


def test_formatear_sse_sin_id_ni_nombre_solo_lleva_data():
    """Sin id ni nombre el navegador lo entrega a onmessage y no mueve el Last-Event-ID."""
    assert formatear_sse({"a": 1}) == 'data: {"a":1}\n\n'


def test_formatear_sse_con_solo_id_o_solo_nombre():
    """Cada campo opcional aparece solo si se pidió."""
    assert formatear_sse({}, id_evento=7) == "id: 7\ndata: {}\n\n"
    assert formatear_sse({}, nombre="run_error") == "event: run_error\ndata: {}\n\n"


def test_formatear_sse_incluye_el_id_cero():
    """El id 0 es un id válido: se compara con None, no con 'falso'."""
    assert formatear_sse({}, id_evento=0).startswith("id: 0\n")


def test_formatear_sse_deja_los_acentos_y_usa_json_compacto():
    """ensure_ascii=False conserva los caracteres; los separadores no llevan espacios."""
    mensaje = formatear_sse({"texto": "acción · ñandú", "n": [1, 2]})
    assert mensaje == 'data: {"texto":"acción · ñandú","n":[1,2]}\n\n'


def test_formatear_sse_escapa_los_saltos_de_linea_del_texto():
    """El JSON va en una sola línea: un salto dentro del texto no puede partir el mensaje."""
    mensaje = formatear_sse({"texto": "linea uno\nlinea dos"}, id_evento=1)
    assert mensaje.count("\n") == 3  # id, data y la línea en blanco final; ninguno dentro del texto
    assert json.loads(mensaje.split("data: ")[1])["texto"] == "linea uno\nlinea dos"


# --------------------------------------------------------------------------------------
# filtrar_desde
# --------------------------------------------------------------------------------------

def test_filtrar_desde_devuelve_solo_los_seq_mayores():
    """Con desde_seq 2 quedan los eventos 3, 4 y 5 (el evento 2 ya lo tiene el cliente)."""
    eventos = [hacer_evento(n) for n in range(1, 6)]
    assert [e["seq"] for e in filtrar_desde(eventos, 2)] == [3, 4, 5]


def test_filtrar_desde_cero_lo_devuelve_todo_y_al_final_nada():
    """Desde 0 sale todo; desde el último seq (o más) no queda nada."""
    eventos = [hacer_evento(n) for n in range(1, 4)]
    assert filtrar_desde(eventos, 0) == eventos
    assert filtrar_desde(eventos, 3) == []
    assert filtrar_desde(eventos, 99) == []


@pytest.mark.parametrize("raro", [
    {"tipo": "sin_seq"},  # seq ausente
    {"seq": "7"},  # seq como texto
    {"seq": 2.5},  # seq decimal
    {"seq": None},  # seq nulo
    "no_es_un_diccionario",  # ni siquiera es un objeto
    None,
])
def test_filtrar_desde_no_descarta_los_eventos_sin_seq_valido(raro):
    """Un evento con seq ausente o no entero debe llegar al validador y verse como error, no perderse."""
    resultado = filtrar_desde([hacer_evento(1), raro], 100)
    assert resultado == [raro]  # el evento 1 se filtra; el raro se conserva


def test_filtrar_desde_devuelve_una_lista_nueva_sin_tocar_la_original():
    """La lista de entrada queda intacta (es la grabación cargada)."""
    eventos = [hacer_evento(n) for n in range(1, 4)]
    copia = list(eventos)
    resultado = filtrar_desde(eventos, 1)
    assert eventos == copia
    assert resultado is not eventos


# --------------------------------------------------------------------------------------
# _espera_entre
# --------------------------------------------------------------------------------------

def test_espera_entre_el_primer_evento_no_espera():
    """Sin evento previo no hay brecha que respetar."""
    assert _espera_entre(None, "2026-11-11T20:00:00-03:00", 2.0) == 0.0


@pytest.mark.parametrize("tope", [0, 0.0, -1.0])
def test_espera_entre_con_tope_cero_o_negativo_nunca_espera(tope):
    """Un tope que no es positivo desactiva el espaciado."""
    assert _espera_entre("2026-11-11T20:00:00-03:00", "2026-11-11T20:00:30-03:00", tope) == 0.0


def test_espera_entre_respeta_la_brecha_original_si_cabe_en_el_tope():
    """Una brecha de 1,5 s con tope de 2 s se espera completa."""
    assert _espera_entre("2026-11-11T20:00:00.000-03:00", "2026-11-11T20:00:01.500-03:00", 2.0) == 1.5


def test_espera_entre_recorta_la_brecha_al_tope():
    """Una brecha de 30 s se recorta al tope de 2 s."""
    assert _espera_entre("2026-11-11T20:00:00-03:00", "2026-11-11T20:00:30-03:00", 2.0) == 2.0


def test_espera_entre_nunca_devuelve_negativos():
    """Si el timestamp actual es anterior al previo, no se espera (en vez de un valor negativo)."""
    assert _espera_entre("2026-11-11T20:00:10-03:00", "2026-11-11T20:00:00-03:00", 2.0) == 0.0


def test_espera_entre_compara_instantes_aunque_cambie_la_zona_horaria():
    """20:00:00-03:00 y 23:00:01+00:00 están separados por un segundo real."""
    assert _espera_entre("2026-11-11T20:00:00-03:00", "2026-11-11T23:00:01+00:00", 2.0) == 1.0


@pytest.mark.parametrize("anterior, actual", [
    ("2026-11-11T20:00:00-03:00", "no es una fecha"),  # timestamp ilegible (ValueError)
    ("2026-11-11T20:00:00", "2026-11-11T20:00:01-03:00"),  # una con zona y otra sin (TypeError)
    ("2026-11-11T20:00:00-03:00", None),  # timestamp ausente (TypeError)
])
def test_espera_entre_con_timestamps_ilegibles_no_espera_y_no_falla(anterior, actual):
    """Un timestamp roto no debe tumbar el flujo: el validador ya lo reportará, aquí solo no se espera."""
    assert _espera_entre(anterior, actual, 2.0) == 0.0


# --------------------------------------------------------------------------------------
# flujo_sse (listas cerradas)
# --------------------------------------------------------------------------------------

def test_flujo_sse_emite_cada_evento_valido_con_su_id(contrato_ok):
    """Cada evento sale tal cual, con id = seq, en el orden de la lista."""
    eventos = [hacer_evento(n) for n in range(1, 4)]
    mensajes = asyncio.run(juntar(flujo_sse(eventos, 0.0)))
    assert len(mensajes) == 3
    parseados = parsear_sse("".join(mensajes))
    assert [m["id"] for m in parseados] == [1, 2, 3]
    assert [m["data"] for m in parseados] == eventos  # el evento viaja sin alterarse


def test_flujo_sse_con_lista_vacia_no_emite_nada(contrato_ok):
    """Sin eventos no hay mensajes ni errores."""
    assert asyncio.run(juntar(flujo_sse([], 2.0))) == []


def test_flujo_sse_no_duerme_antes_del_primero_y_recorta_las_brechas(contrato_ok):
    """Brechas de 1 s y 30 s con tope 2 s: se espera 1,0 y 2,0; nunca antes del primer evento."""
    eventos = [hacer_evento(1, 0), hacer_evento(2, 1), hacer_evento(3, 31)]
    esperas, dormir = reloj_falso()
    asyncio.run(juntar(flujo_sse(eventos, 2.0, dormir)))
    assert esperas == [1.0, 2.0]


def test_flujo_sse_con_tope_cero_nunca_duerme(contrato_ok):
    """Con tope 0 todo sale de corrido, sin llamar a dormir."""
    esperas, dormir = reloj_falso()
    asyncio.run(juntar(flujo_sse([hacer_evento(1, 0), hacer_evento(2, 30)], 0.0, dormir)))
    assert esperas == []


def test_flujo_sse_por_defecto_dormir_es_asyncio_sleep():
    """Sin inyectar nada, el emisor espera de verdad con asyncio.sleep."""
    assert inspect.signature(flujo_sse).parameters["dormir"].default is asyncio.sleep


def test_flujo_sse_un_evento_invalido_emite_evento_invalido_y_corta(monkeypatch):
    """El 3.º rompe el contrato: salen 2 eventos, luego evento_invalido sin id, y nada más (ni se valida el 4.º)."""
    vistos = []

    def rechaza_el_tercero(evento: dict) -> list[str]:
        """Acepta los eventos 1 y 2 y rechaza el 3 con dos motivos."""
        vistos.append(evento["seq"])
        return ["primer motivo", "segundo motivo"] if evento["seq"] == 3 else []

    monkeypatch.setattr(emisor, "comprobar_evento", rechaza_el_tercero)
    mensajes = parsear_sse("".join(asyncio.run(juntar(flujo_sse([hacer_evento(n) for n in range(1, 6)], 0.0)))))
    assert [m["id"] for m in mensajes[:2]] == [1, 2]
    error = mensajes[-1]
    assert len(mensajes) == 3  # 2 válidos + el error; los eventos 4 y 5 no salen
    assert error["event"] == "evento_invalido"
    assert error["id"] is None  # el error no mueve el Last-Event-ID del cliente
    assert error["data"] == {"seq": 3, "tipo": "run_iniciada", "motivos": ["primer motivo", "segundo motivo"]}
    assert vistos == [1, 2, 3]  # después del rechazo no se valida ningún evento más


def test_flujo_sse_si_el_primero_es_invalido_solo_sale_el_error(monkeypatch):
    """Un primer evento roto produce únicamente el evento_invalido."""
    monkeypatch.setattr(emisor, "comprobar_evento", lambda evento: ["roto"])
    mensajes = parsear_sse("".join(asyncio.run(juntar(flujo_sse([hacer_evento(1), hacer_evento(2)], 0.0)))))
    assert [(m["event"], m["data"]["seq"]) for m in mensajes] == [("evento_invalido", 1)]


@pytest.mark.parametrize("raro, seq, tipo", [
    ("no_es_un_diccionario", None, None),  # ni siquiera es un objeto: seq y tipo salen None
    ({"payload": {}}, None, None),  # objeto sin seq ni tipo
    ({"seq": 9, "tipo": "x"}, 9, "x"),  # objeto con lo básico
])
def test_flujo_sse_describe_el_evento_invalido_aunque_le_falten_campos(monkeypatch, raro, seq, tipo):
    """El aviso usa seq y tipo si existen y None si no, sin lanzar excepciones."""
    monkeypatch.setattr(emisor, "comprobar_evento", lambda evento: ["motivo"])
    mensajes = parsear_sse("".join(asyncio.run(juntar(flujo_sse([raro], 0.0)))))
    assert mensajes[0]["data"] == {"seq": seq, "tipo": tipo, "motivos": ["motivo"]}


def test_flujo_sse_valida_antes_de_dormir(monkeypatch):
    """Un evento inválido corta de inmediato: no se pierde tiempo esperando su brecha."""
    monkeypatch.setattr(emisor, "comprobar_evento", lambda evento: ["roto"] if evento["seq"] == 2 else [])
    esperas, dormir = reloj_falso()
    asyncio.run(juntar(flujo_sse([hacer_evento(1, 0), hacer_evento(2, 1)], 2.0, dormir)))
    assert esperas == []


# --------------------------------------------------------------------------------------
# flujo_vivo: ejecución ya cerrada
# --------------------------------------------------------------------------------------

def test_flujo_vivo_de_una_ejecucion_terminada_entrega_todo_y_cierra_sin_latidos(contrato_ok):
    """Con la ejecución cerrada y 4 eventos: salen los 4 en orden, con id = seq, y el flujo termina."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        await llenar(ejecucion, 4)
        await ejecucion.cerrar()
        return ejecucion, await leer(ejecucion)

    ejecucion, mensajes = asyncio.run(escenario())
    assert LATIDO_SSE not in mensajes
    parseados = parsear_sse("".join(mensajes))
    assert [m["id"] for m in parseados] == [1, 2, 3, 4]
    assert [m["data"] for m in parseados] == ejecucion.eventos  # tal cual, sin tocar `origen`


def test_flujo_vivo_reanuda_desde_un_seq(contrato_ok):
    """Con desde_seq 2 solo llegan los eventos 3 y 4."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        await llenar(ejecucion, 4)
        await ejecucion.cerrar()
        return await leer(ejecucion, desde_seq=2)

    assert [m["id"] for m in parsear_sse("".join(asyncio.run(escenario())))] == [3, 4]


def test_flujo_vivo_terminada_y_sin_pendientes_no_emite_nada(contrato_ok):
    """Si el cliente ya tiene todo y la ejecución terminó bien, el flujo acaba vacío."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        await llenar(ejecucion, 2)
        await ejecucion.cerrar()
        return await leer(ejecucion, desde_seq=2)

    assert asyncio.run(escenario()) == []


def test_flujo_vivo_entrega_el_evento_invalido_de_una_ejecucion_fallida(monkeypatch):
    """Tras los eventos válidos sale el evento_invalido guardado en la ejecución, sin id."""
    respuestas = iter([[], [], ["motivo del contrato"]])  # el tercero se rechaza
    monkeypatch.setattr(modulo_registro, "comprobar_evento", lambda evento: next(respuestas))

    async def escenario():
        ejecucion = hacer_ejecucion()
        await llenar(ejecucion, 2)
        with pytest.raises(EventoInvalido):
            await ejecucion.emitir("estratega", "brief_emitido", {})
        return await leer(ejecucion)

    mensajes = asyncio.run(escenario())
    assert len(mensajes) == 3
    error = parsear_sse(mensajes[-1])[0]
    assert (error["event"], error["id"]) == ("evento_invalido", None)
    assert error["data"] == {"seq": 3, "tipo": "brief_emitido", "motivos": ["motivo del contrato"]}


def test_flujo_vivo_entrega_el_run_error_de_una_ejecucion_fallida(contrato_ok):
    """Un fallo inesperado sale como event: run_error, con el mensaje y sin id."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        await llenar(ejecucion, 1)
        await ejecucion.fallar("algo salió mal")
        return await leer(ejecucion)

    mensajes = asyncio.run(escenario())
    assert mensajes[-1] == 'event: run_error\ndata: {"motivos":["algo salió mal"]}\n\n'
    assert "id:" not in mensajes[-1]


def test_flujo_vivo_una_ejecucion_fallida_reentrega_su_error_al_reconectar(contrato_ok):
    """El error no lleva id y pudo perderse: aunque el cliente ya tenga todos los eventos, lo recibe de nuevo."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        await llenar(ejecucion, 2)
        await ejecucion.fallar("fallo")
        return await leer(ejecucion, desde_seq=2)

    mensajes = asyncio.run(escenario())
    assert [(m["event"], m["id"]) for m in parsear_sse("".join(mensajes))] == [("run_error", None)]


def test_flujo_vivo_no_revalida_ni_espacia_los_eventos_del_buffer(monkeypatch):
    """Los eventos del buffer ya se validaron al emitirse: aquí salen tal cual, sin llamar al validador."""

    def no_debe_llamarse(evento: dict) -> list[str]:
        """Falla la prueba si el flujo vivo vuelve a validar un evento."""
        raise AssertionError("flujo_vivo no debe revalidar")

    monkeypatch.setattr(emisor, "comprobar_evento", no_debe_llamarse)

    async def escenario():
        ejecucion = hacer_ejecucion()
        # Un evento que el esquema rechazaría, metido directo al buffer: el flujo no lo cuestiona.
        ejecucion.eventos.append({"seq": 1, "contenido": "fuera de contrato"})
        await ejecucion.cerrar()
        return await leer(ejecucion)

    mensajes = asyncio.run(escenario())
    assert parsear_sse("".join(mensajes))[0]["data"] == {"seq": 1, "contenido": "fuera de contrato"}


# --------------------------------------------------------------------------------------
# flujo_vivo: ejecución en curso
# --------------------------------------------------------------------------------------

def test_flujo_vivo_manda_latidos_mientras_no_llegan_eventos(contrato_ok):
    """Sin eventos y en curso, cada intervalo de latido sale un ': ping'; al cerrar el flujo termina."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        lector = asyncio.create_task(leer(ejecucion, latido=0.02))
        await asyncio.sleep(0.15)  # tiempo para varios latidos
        assert not lector.done()  # sigue abierto mientras la ejecución está en curso
        await ejecucion.cerrar()
        return await lector

    mensajes = asyncio.run(escenario())
    assert len(mensajes) >= 2
    assert set(mensajes) == {LATIDO_SSE}  # solo latidos: no hubo eventos


def test_flujo_vivo_entrega_un_evento_que_llega_mientras_espera(contrato_ok):
    """Un lector dormido despierta al emitirse un evento y lo entrega sin esperar al siguiente latido."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        lector = asyncio.create_task(leer(ejecucion, latido=30.0))  # latido enorme: no puede ser un latido
        await asyncio.sleep(0.01)  # deja que el lector se duerma primero
        assert not lector.done()
        await llenar(ejecucion, 1)
        await ejecucion.cerrar()
        return await lector

    mensajes = asyncio.run(escenario())
    assert [m["id"] for m in parsear_sse("".join(mensajes))] == [1]
    assert LATIDO_SSE not in mensajes


def test_flujo_vivo_sigue_hasta_el_cierre_y_entrega_todos_los_eventos(contrato_ok):
    """Un lector concurrente ve los 5 eventos a medida que se emiten y termina al cerrarse la ejecución."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        lector = asyncio.create_task(leer(ejecucion, latido=30.0))
        for _ in range(5):  # el orquestador emite uno a uno, cediendo el control entre cada uno
            await ejecucion.emitir("sistema", "run_iniciada", {})
            await asyncio.sleep(0)
        await ejecucion.cerrar()
        return await lector

    assert [m["id"] for m in parsear_sse("".join(asyncio.run(escenario())))] == [1, 2, 3, 4, 5]


def test_flujo_vivo_en_curso_reanuda_y_solo_entrega_lo_nuevo(contrato_ok):
    """Reconectando con desde_seq=2 en una ejecución en curso, espera y entrega solo el evento 3."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        await llenar(ejecucion, 2)
        lector = asyncio.create_task(leer(ejecucion, desde_seq=2, latido=30.0))
        await asyncio.sleep(0.01)
        assert not lector.done()  # nada pendiente: se queda esperando
        await llenar(ejecucion, 1)
        await ejecucion.cerrar()
        return await lector

    assert [m["id"] for m in parsear_sse("".join(asyncio.run(escenario())))] == [3]


def test_flujo_vivo_el_fallo_llega_al_lector_que_esperaba(contrato_ok):
    """Si la ejecución falla mientras el lector espera, este recibe el evento y luego el run_error."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        lector = asyncio.create_task(leer(ejecucion, latido=30.0))
        await asyncio.sleep(0.01)
        await llenar(ejecucion, 1)
        await ejecucion.fallar("se rompió")
        return await lector

    parseados = parsear_sse("".join(asyncio.run(escenario())))
    assert [(m["event"], m["id"]) for m in parseados] == [("message", 1), ("run_error", None)]


def test_flujo_vivo_dos_lectores_reciben_lo_mismo(contrato_ok):
    """Varias pestañas pueden escuchar la misma ejecución a la vez."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        lector_a = asyncio.create_task(leer(ejecucion, latido=30.0))
        lector_b = asyncio.create_task(leer(ejecucion, latido=30.0))
        await asyncio.sleep(0.01)
        await llenar(ejecucion, 3)
        await ejecucion.cerrar()
        return await lector_a, await lector_b

    a, b = asyncio.run(escenario())
    assert a == b and len(a) == 3


def test_flujo_vivo_un_cliente_que_se_desconecta_no_bloquea_la_ejecucion(contrato_ok):
    """Cancelar un lector dormido (el cliente cierra la pestaña) no deja la Condition tomada: la ejecución sigue."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        desconectado = asyncio.create_task(leer(ejecucion, latido=30.0))
        await asyncio.sleep(0.01)  # el lector queda esperando un cambio
        desconectado.cancel()
        with pytest.raises(asyncio.CancelledError):
            await desconectado
        # Si la Condition hubiera quedado bloqueada, estas tres líneas se colgarían (por eso el tope de 1 s).
        await asyncio.wait_for(llenar(ejecucion, 2), timeout=1.0)
        await asyncio.wait_for(ejecucion.cerrar(), timeout=1.0)
        assert ejecucion.estado == EstadoRun.TERMINADA
        return await leer(ejecucion)  # un lector nuevo ve todo

    assert [m["id"] for m in parsear_sse("".join(asyncio.run(escenario())))] == [1, 2]


# --------------------------------------------------------------------------------------
# Con la plantilla, el kit y el validador reales
# --------------------------------------------------------------------------------------

def test_real_flujo_vivo_de_una_ejecucion_completa_entrega_32_eventos_validos():
    """Orquestador, plantilla, kit y validador reales: el SSE trae los 32 eventos, iguales al buffer y válidos."""
    ruta = config.CONTRATOS_DIR / "input" / "examples" / "valido_minimo_todo_auto.json"
    with open(ruta, encoding="utf-8") as f:
        entrada = json.load(f)
    entrada.pop("$comment", None)  # el esquema no declara el comentario raíz
    resolucion, errores = resolver(entrada, cargar_fichas())
    assert errores == []

    async def escenario():
        ejecucion = Ejecucion("run_real_emisor", entrada, resolucion, "grabado")
        await ejecutar_run(ejecucion, ritmo_seg=0)
        return ejecucion, await leer(ejecucion)

    ejecucion, mensajes = asyncio.run(escenario())
    assert ejecucion.estado == EstadoRun.TERMINADA, ejecucion.fallo
    parseados = parsear_sse("".join(mensajes))
    assert [m["id"] for m in parseados] == list(range(1, 33))
    for mensaje, evento in zip(parseados, ejecucion.eventos):  # cada mensaje es su evento del buffer
        assert mensaje["data"] == evento
        assert comprobar_evento(mensaje["data"]) == []  # y cumple el contrato real
    assert parseados[-1]["data"]["tipo"] == "run_finalizada"


def test_real_flujo_vivo_reanuda_una_ejecucion_completa_desde_el_seq_30():
    """Con la ejecución real terminada, reanudar desde 30 entrega solo los eventos 31 y 32."""
    ruta = config.CONTRATOS_DIR / "input" / "examples" / "valido_minimo_todo_auto.json"
    with open(ruta, encoding="utf-8") as f:
        entrada = json.load(f)
    entrada.pop("$comment", None)
    resolucion, errores = resolver(entrada, cargar_fichas())
    assert errores == []

    async def escenario():
        ejecucion = Ejecucion("run_real_emisor2", entrada, resolucion, "grabado")
        await ejecutar_run(ejecucion, ritmo_seg=0)
        return await leer(ejecucion, desde_seq=30)

    assert [m["id"] for m in parsear_sse("".join(asyncio.run(escenario())))] == [31, 32]