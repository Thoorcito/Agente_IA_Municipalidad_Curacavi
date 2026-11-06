"""Scripts de línea de comandos (preparar datos, evaluar y ficha técnica)."""

import pytest

from agente.configuracion import settings
from scripts import evaluar, ficha_tecnica, preparar_datos


@pytest.fixture
def entorno_temporal(tmp_path, monkeypatch):
    """Redirige la base, los índices y las evidencias a una carpeta temporal."""
    monkeypatch.setattr(settings, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(settings, "EVIDENCE_DIR", tmp_path / "evidencias")
    monkeypatch.setenv("FECHA_REFERENCIA", "2026-11-04")
    yield tmp_path


def test_preparar_datos_offline(entorno_temporal):
    # Act
    resumen = preparar_datos.main(["--offline"])

    # Assert
    assert resumen["solicitudes"] == 30
    assert resumen["fragmentos"]["leyes"] > 100 and resumen["fragmentos"]["casos_resueltos"] > 0


def test_evaluar_escenarios_offline_guarda_evidencia(entorno_temporal):
    # Act
    df = evaluar.main(["escenarios", "--offline"])

    # Assert
    assert df["accion_ok"].all()
    assert (entorno_temporal / "evidencias" / "escenarios_offline.csv").exists()


def test_evaluar_recuperacion_y_respuestas_offline(entorno_temporal):
    # Act
    resumen = evaluar.main(["recuperacion", "--offline"])
    respuestas = evaluar.main(["respuestas", "--offline"])

    # Assert
    assert len(resumen) == 4 and len(respuestas) == 18
    assert respuestas["cita_valida"].mean() == 1.0


def test_ficha_tecnica_actualiza_el_bloque_del_readme(tmp_path):
    # Arrange
    readme = tmp_path / "README.md"
    readme.write_text("antes\n<!-- FICHA:INICIO -->\nvieja\n<!-- FICHA:FIN -->\ndespués", encoding="utf-8")

    # Act
    cambiado = ficha_tecnica.actualizar_readme(readme)
    sin_cambios = ficha_tecnica.actualizar_readme(readme)

    # Assert
    texto = readme.read_text(encoding="utf-8")
    assert cambiado and not sin_cambios
    assert settings.LLM_MODEL in texto and settings.JUEZ_MODEL in texto and "vieja" not in texto
