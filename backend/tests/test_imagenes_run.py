"""Imágenes de un run: guardarlas en la ejecución y servirlas por GET /api/runs/{id}/imagenes/{ref}."""
import pytest

from app.runs.registro import IMAGEN_MAX_BYTES, IMAGENES_MAX_POR_RUN
from tests.test_rutas import ajustes, cliente_http, correr, falsos, hacer_entrada, kit_de_prueba, registro  # noqa: F401

JPEG = b"\xff\xd8\xff\xe0" + b"datos" * 20


def _ejecucion(registro):
    return registro.crear(hacer_entrada(), None, "real")


def _get(ruta: str):
    async def llamada():
        async with cliente_http() as c:
            return await c.get(ruta)
    return llamada()


def test_guardar_y_obtener(falsos, registro):
    async def escenario():
        ej = _ejecucion(registro)
        ej.guardar_imagen("foto-2", JPEG, "image/jpeg")
        return ej.obtener_imagen("foto-2"), ej.obtener_imagen("otra")

    assert correr(escenario()) == ((JPEG, "image/jpeg"), None)


@pytest.mark.parametrize("referencia", ["", "../secreto", "con espacio", "A-mayuscula", "x" * 41, "a/b"])
def test_referencia_invalida_se_rechaza(falsos, registro, referencia):
    async def escenario():
        _ejecucion(registro).guardar_imagen(referencia, JPEG, "image/jpeg")

    with pytest.raises(ValueError, match="Referencia"):
        correr(escenario())


@pytest.mark.parametrize("mime, datos, motivo", [
    ("image/svg+xml", JPEG, "Tipo"),
    ("text/html", JPEG, "Tipo"),
    ("image/jpeg", b"", "pesar"),
    ("image/jpeg", b"x" * (IMAGEN_MAX_BYTES + 1), "pesar"),
])
def test_tipo_o_tamano_invalido_se_rechaza(falsos, registro, mime, datos, motivo):
    async def escenario():
        _ejecucion(registro).guardar_imagen("foto", datos, mime)

    with pytest.raises(ValueError, match=motivo):
        correr(escenario())


def test_tope_de_imagenes_por_run_pero_reemplazar_una_existente_si_se_puede(falsos, registro):
    async def escenario():
        ej = _ejecucion(registro)
        for i in range(IMAGENES_MAX_POR_RUN):
            ej.guardar_imagen(f"f{i}", JPEG, "image/jpeg")
        ej.guardar_imagen("f0", JPEG + b"v2", "image/jpeg")  # reemplazo: no cuenta como nueva
        with pytest.raises(ValueError, match="como mucho"):
            ej.guardar_imagen("nueva", JPEG, "image/jpeg")
        return ej.obtener_imagen("f0")[0]

    assert correr(escenario()) == JPEG + b"v2"


def test_get_sirve_los_bytes_con_su_tipo_y_cabeceras_de_seguridad(falsos, registro):
    async def escenario():
        ej = _ejecucion(registro)
        ej.guardar_imagen("foto-2", JPEG, "image/jpeg")
        return await _get(f"/api/runs/{ej.run_id}/imagenes/foto-2")

    r = correr(escenario())
    assert r.status_code == 200 and r.content == JPEG
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-content-type-options"] == "nosniff" and "private" in r.headers["cache-control"]


def test_get_404_si_el_run_o_la_imagen_no_existen(falsos, registro):
    async def escenario():
        ej = _ejecucion(registro)
        return await _get("/api/runs/run_noexiste/imagenes/foto"), await _get(f"/api/runs/{ej.run_id}/imagenes/foto")

    sin_run, sin_imagen = correr(escenario())
    assert sin_run.status_code == 404 and "No existe la ejecución" in sin_run.json()["detail"]
    assert sin_imagen.status_code == 404 and "no tiene la imagen" in sin_imagen.json()["detail"]
