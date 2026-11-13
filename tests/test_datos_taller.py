"""Precarga determinista de datos del taller: se resuelve sin red y sin modelo."""
import os

os.environ.setdefault("GOOGLE_API_KEY", "clave-de-prueba")

from src.agente_acciones.graph import _bloque_datos, _consulta_del_texto


def test_detecta_ticker_y_mercado_estadounidense():
    assert _consulta_del_texto("Analiza NVDA en US para un perfil moderado a 12 meses.") == ("NVDA", "US")


def test_detecta_ticker_chileno_con_guion():
    assert _consulta_del_texto("¿Cómo está SQM-B en la bolsa de Santiago?") == ("SQM-B", "CL")


def test_sin_ticker_no_precarga_nada():
    assert _consulta_del_texto("¿Cuánto vale esa acción?") is None


def test_ticker_pegado_a_otras_letras_no_cuenta():
    assert _consulta_del_texto("Necesito la acción KOA y el reporte de KO2.") is None


def test_bloque_lleva_precio_y_fecha_de_la_herramienta():
    bloque = _bloque_datos("AAPL", "US")
    assert bloque.startswith("<datos_herramientas>")
    assert bloque.endswith("</datos_herramientas>")
    assert "342.1" in bloque
    assert "2026-11-07" in bloque


def test_la_sintesis_solo_mira_la_pregunta_del_usuario():
    # El aporte de otro agente menciona Chile: no debe cambiar el mercado que pidió el usuario.
    sintesis = (
        "Consulta del usuario:\n<consulta>\nAnaliza NVDA en US para un perfil moderado.\n</consulta>\n\n"
        "Respuestas de los demás agentes del proyecto:\n<respuestas_agentes>\n"
        "### agente_bryhan\nBanca Chilena, Banco Santander Chile, CL, automatización.\n"
        "NVDA y AAPL como ejemplos de tickers.\n</respuestas_agentes>"
    )
    assert _consulta_del_texto(sintesis) == ("NVDA", "US")


def test_sin_bloque_de_consulta_sigue_leyendo_el_texto():
    assert _consulta_del_texto("Revisa SQM-B para mi cartera en Chile") == ("SQM-B", "CL")


def test_seguimiento_reutiliza_el_ticker_del_turno_anterior():
    """«¿y si el horizonte fuera 3 meses?» no trae ticker: se hereda el del hilo."""
    from langchain_core.messages import HumanMessage

    from src.agente_acciones.graph import DatosDelTaller

    class Pedido:
        def __init__(self, mensajes):
            self.messages = mensajes

        def override(self, **cambios):
            return Pedido(cambios.get("messages", self.messages))

    historial = [
        HumanMessage(content="Analiza NVDA en US para un perfil moderado a 12 meses."),
        HumanMessage(content="¿y si el horizonte fuera 3 meses?"),
    ]
    resultado = DatosDelTaller()._con_datos(Pedido(historial))
    ultimo = resultado.messages[-1]
    assert "<datos_herramientas>" in ultimo.content
    assert "182.4" in ultimo.content
