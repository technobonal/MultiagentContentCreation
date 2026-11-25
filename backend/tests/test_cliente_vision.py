"""Cliente de visión de OpenRouter: cascada de modelos, con la llamada HTTP inyectada (sin red)."""
import asyncio
import io

import httpx
import pytest

from app.agentes.cliente_vision import ClienteVision, VisionError, preparar_imagen

MODELOS = ("m1:free", "m2:free", "m3:free")


def ok(texto):
    return 200, {"choices": [{"message": {"content": texto}}]}


def cliente(respuestas, api_key="clave-secreta"):
    """Cliente cuyos modelos responden en orden lo que diga `respuestas` ({modelo: (código, json) o excepción})."""
    pedidos = []

    async def enviar(url, cabeceras, cuerpo, timeout):
        pedidos.append(cuerpo)
        r = respuestas[cuerpo["model"]]
        if isinstance(r, Exception):
            raise r
        return r

    c = ClienteVision(api_key=api_key, modelos=MODELOS, enviar=enviar)
    return c, pedidos


def describir(c):
    return asyncio.run(c.describir(b"\xff\xd8bytes", "¿Qué hay?"))


def test_responde_el_primer_modelo_y_no_prueba_los_demas():
    c, pedidos = cliente({"m1:free": ok(" Un edificio. ")})
    r = describir(c)
    assert (r.texto, r.modelo, r.saltos) == ("Un edificio.", "m1:free", ())
    assert [p["model"] for p in pedidos] == ["m1:free"]


def test_el_pedido_lleva_la_imagen_y_apaga_el_razonamiento():
    c, pedidos = cliente({"m1:free": ok("x")})
    describir(c)
    cuerpo = pedidos[0]
    assert cuerpo["reasoning"] == {"enabled": False} and cuerpo["temperature"] == 0
    partes = cuerpo["messages"][0]["content"]
    assert partes[0] == {"type": "text", "text": "¿Qué hay?"}
    assert partes[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


@pytest.mark.parametrize("falla", [(429, {"error": "limite"}), (503, None), ok("   "), (200, {"choices": []})])
def test_salta_al_siguiente_por_falla_tecnica_o_respuesta_vacia(falla):
    c, pedidos = cliente({"m1:free": falla, "m2:free": ok("Segundo.")})
    r = describir(c)
    assert (r.texto, r.modelo) == ("Segundo.", "m2:free")
    assert len(r.saltos) == 1 and r.saltos[0].startswith("m1:free")


def test_salta_por_timeout_y_por_error_de_red():
    c, _ = cliente({"m1:free": httpx.ReadTimeout("lento"), "m2:free": httpx.ConnectError("red"), "m3:free": ok("Tercero.")})
    r = describir(c)
    assert r.modelo == "m3:free" and [s.split(":")[0] for s in r.saltos] == ["m1", "m2"]


def test_error_de_credenciales_corta_sin_probar_otros_modelos():
    c, pedidos = cliente({"m1:free": (401, {"error": "key mala"})})
    with pytest.raises(VisionError) as e:
        describir(c)
    assert e.value.codigo == "pedido_rechazado" and "401" in e.value.mensaje
    assert len(pedidos) == 1


def test_si_ninguno_responde_lanza_con_el_motivo_de_cada_uno():
    c, _ = cliente({"m1:free": (429, None), "m2:free": ok(""), "m3:free": (502, None)})
    with pytest.raises(VisionError) as e:
        describir(c)
    assert e.value.codigo == "sin_respuesta"
    assert "m1:free: HTTP 429" in e.value.mensaje and "m2:free: respuesta vacía" in e.value.mensaje


def test_sin_key_falla_y_la_key_nunca_aparece_en_los_mensajes():
    c, _ = cliente({}, api_key="")
    with pytest.raises(VisionError) as e:
        describir(c)
    assert e.value.codigo == "sin_api_key"
    c2, _ = cliente({"m1:free": (401, None)}, api_key="clave-secreta")
    with pytest.raises(VisionError) as e2:
        describir(c2)
    assert "clave-secreta" not in e2.value.mensaje


def test_preparar_imagen_reduce_y_devuelve_jpeg():
    from PIL import Image

    original = io.BytesIO()
    Image.new("RGB", (3000, 1500), (10, 20, 30)).save(original, "PNG")
    datos, mime = preparar_imagen(original.getvalue(), lado_max=500)
    reducida = Image.open(io.BytesIO(datos))
    assert mime == "image/jpeg" and max(reducida.size) == 500 and reducida.format == "JPEG"
