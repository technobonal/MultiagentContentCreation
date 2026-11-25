"""Cadenas de modelos por defecto: el 120b entra al redactor solo como último recurso."""

from app import config


def test_redactor_termina_en_el_modelo_del_revisor_como_ultimo_recurso():
    cadena = config.GROQ_FALLBACK_REDACTOR
    # Orden: principal, respaldo y, al final, el modelo principal del revisor.
    assert cadena[0] == config.GROQ_MODELO_REDACTOR
    assert cadena[-1] == config.GROQ_MODELO_RESPALDO_FINAL
    assert len(cadena) == len(set(cadena))


def test_revisor_no_cae_al_modelo_del_redactor():
    assert config.GROQ_MODELO_REDACTOR not in config.GROQ_FALLBACK_REVISOR
