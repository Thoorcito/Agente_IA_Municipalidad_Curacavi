"""Genera las capturas de la interfaz para el README (modo offline: sin LLM ni internet).

Uso:  python -m scripts.capturas
Requiere: pip install playwright && playwright install chromium   (o la variable CHROME_PATH)
Respeta PERSISTENCIA y DATABASE_URL: con PERSISTENCIA=postgres las capturas muestran la base de Docker.
Las capturas quedan en EVIDENCIAS_TEST/capturas/ (raíz del repositorio). Reemplácelas por capturas de la ejecución real si lo desea.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from agente.configuracion import settings

PUERTO = 8599
SALIDA = settings.EVIDENCIAS_DIR / "capturas"


def esperar_respuesta(pagina, n_mensajes: int, limite: int = 60):
    """Espera a que el chat tenga n_mensajes y la app termine de ejecutarse."""
    for _ in range(limite * 2):
        if pagina.locator('[data-testid="stChatMessage"]').count() >= n_mensajes and \
                pagina.locator('[data-testid="stStatusWidget"]').count() == 0:
            return
        time.sleep(0.5)


def escribir(pagina, texto: str, n_mensajes: int):
    caja = pagina.locator('textarea[data-testid="stChatInputTextArea"]')
    caja.fill(texto)
    caja.press("Enter")
    esperar_respuesta(pagina, n_mensajes)
    time.sleep(1.5)


def main():
    from playwright.sync_api import sync_playwright

    SALIDA.mkdir(parents=True, exist_ok=True)
    entorno = {**os.environ, "LLM_PROVIDER": "offline", "EMBEDDINGS_PROVIDER": "offline",
               "RUNTIME_DIR": tempfile.mkdtemp(), "FECHA_REFERENCIA": os.getenv("FECHA_REFERENCIA", "2026-11-04")}
    subprocess.run([sys.executable, "-m", "scripts.preparar_datos", "--offline"], env=entorno, check=True,
                   cwd=settings.BASE_DIR)
    servidor = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true",
                                 "--server.port", str(PUERTO), "--browser.gatherUsageStats", "false"],
                                env=entorno, cwd=settings.BASE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        with sync_playwright() as p:
            navegador = p.chromium.launch(executable_path=os.getenv("CHROME_PATH") or None)
            pagina = navegador.new_page(viewport={"width": 1500, "height": 1000})
            pagina.goto(f"http://localhost:{PUERTO}", wait_until="networkidle")
            time.sleep(4)
            pagina.screenshot(path=str(SALIDA / "app_01_inicio.png"))

            # 1) Trámite con documentos faltantes: el agente registra el folio como Observada
            escribir(pagina, "Quiero sacar mi primera licencia de conducir clase B. Tengo mi cédula, dos fotos, el certificado de "
                             "antecedentes y el certificado de residencia de la junta de vecinos.", 2)
            pagina.screenshot(path=str(SALIDA / "app_02_faltan_antecedentes.png"), full_page=True)

            # 2) Continuidad: aporta el documento y el agente agenda la hora en el mismo folio
            escribir(pagina, "Ya tengo el certificado de estudios de 8° básico.", 4)
            pagina.get_by_role("tab", name="Traza").click()
            time.sleep(1)
            pagina.screenshot(path=str(SALIDA / "app_03_continuidad_y_traza.png"), full_page=True)

            # 3) Fuentes en conflicto (nuevo hilo)
            pagina.get_by_role("button", name="➕ Nueva atención").click()
            time.sleep(3)
            escribir(pagina, "¿Cuál es el plazo para renovar el permiso de circulación según la ley y según la municipalidad?", 2)
            pagina.screenshot(path=str(SALIDA / "app_04_fuentes_por_nivel.png"), full_page=True)

            # 4) Plazo vencido: queda pendiente la aprobación del funcionario
            pagina.get_by_role("button", name="➕ Nueva atención").click()
            time.sleep(3)
            escribir(pagina, "¿En qué estado está mi reclamo SOL-2026-0006?", 1)
            time.sleep(2)
            pagina.screenshot(path=str(SALIDA / "app_05_aprobacion_humana.png"), full_page=True)

            # 5) Memoria del vecino y persistencia activa (al final de la barra lateral)
            pagina.get_by_role("button", name="✋ Rechazar").click()
            esperar_respuesta(pagina, 2)
            time.sleep(2)
            pagina.get_by_role("tab", name="Memoria").click()
            pagina.locator('[data-testid="stSidebarContent"]').evaluate("e => e.scrollTo(0, e.scrollHeight)")
            time.sleep(1)
            pagina.screenshot(path=str(SALIDA / "app_06_memoria_y_persistencia.png"), full_page=True)
            navegador.close()
    finally:
        servidor.terminate()
    print(f"✅ Capturas en {SALIDA}")


if __name__ == "__main__":
    main()
