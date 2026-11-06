"""Catálogo de fuentes y citas: ley, norma municipal, guía y ChileAtiende se citan distinto."""
from agente.dominio import citas as cat


def test_cita_de_ley_usa_articulo_y_titulo_del_catalogo():
    # Arrange
    fuente_id, articulo = "ley_18695", "12"

    # Act
    cita = cat.formatear_cita(fuente_id, articulo=articulo, pagina=12)

    # Assert: se cita por artículo (no por página) y con el texto refundido correcto
    assert cita == "DFL N° 1/2006 (Interior), texto refundido de la Ley N° 18.695, art. 12"


def test_cita_de_guia_municipal_usa_pagina():
    # Arrange / Act
    cita = cat.formatear_cita("guia_licencias", pagina=2)

    # Assert
    assert cita.startswith("Municipalidad de Curacaví, guía") and cita.endswith("pág. 2")


def test_nota_de_version_solo_para_textos_no_vigentes():
    # Act
    nota_vigente = cat.nota_version("ley_19880")
    nota_intermedia = cat.nota_version("dl_3063")

    # Assert
    assert nota_vigente == ""
    assert "versión intermedia" in nota_intermedia and "bcn.cl" in nota_intermedia


def test_etiquetas_dependen_del_nivel_y_no_se_duplican():
    # Arrange
    fragmentos = [
        {"fuente_id": "ley_19880", "articulo": "25", "texto": "a"},
        {"fuente_id": "guia_permiso_circulacion", "pagina": 1, "texto": "b"},
        {"fuente_id": "chileatiende_permiso", "pagina": 1, "texto": "c"},
        {"fuente_id": "procedimiento_simulado", "texto": "d"},
        {"fuente_id": "ley_19880", "articulo": "25", "texto": "a bis"},
    ]

    # Act
    etiquetas = [f["etiqueta"] for f in cat.etiquetar(fragmentos)]

    # Assert
    assert etiquetas == ["L1", "M1", "O1", "S1", "L1"]


def test_validar_citas_rechaza_etiquetas_y_leyes_no_recuperadas():
    # Arrange
    etiquetados = cat.etiquetar([{"fuente_id": "guia_licencias", "pagina": 1, "texto": "Requisitos de licencia"}])
    texto = "Debe presentar su cédula [M1] y lo exige la Ley N° 21.000 [L7]."

    # Act
    r = cat.validar_citas(texto, etiquetados)

    # Assert
    assert r["etiquetas_invalidas"] == ["L7"]
    assert r["normas_no_respaldadas"] == ["21000"]
    assert r["cita_valida"] is False
    assert "[L7]" not in r["texto"] and "[M1]" in r["texto"]


def test_validar_citas_acepta_ley_respaldada_por_fragmento():
    # Arrange
    etiquetados = cat.etiquetar([{"fuente_id": "ley_19880", "articulo": "25", "texto": "plazos de días hábiles"}])

    # Act
    r = cat.validar_citas("Según la Ley N° 19.880 los días son hábiles [L1].", etiquetados)

    # Assert
    assert r["cita_valida"] is True and r["etiquetas_usadas"] == ["L1"]


def test_bloque_de_fuentes_agrupa_por_nivel_en_orden_jerarquico():
    # Arrange
    etiquetados = cat.etiquetar([{"fuente_id": "chileatiende_licencias", "texto": "x"},
                                 {"fuente_id": "dl_3063", "articulo": "15", "texto": "y"}])

    # Act
    bloque = cat.bloque_fuentes(etiquetados)

    # Assert: la ley aparece antes que ChileAtiende y con su advertencia de versión
    assert bloque.index("Normativa nacional") < bloque.index("Orientación general")
    assert "versión intermedia" in bloque
    assert cat.bloque_fuentes(etiquetados, usadas=[]) == ""


def test_busqueda_de_fuente_por_archivo():
    # Act / Assert
    assert cat.fuente_por_archivo("leyes/ley_18290_transito.pdf")["id"] == "ley_18290"
    assert cat.fuente_por_archivo("no_existe.pdf") is None
