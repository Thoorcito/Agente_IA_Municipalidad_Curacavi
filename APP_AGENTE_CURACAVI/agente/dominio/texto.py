"""Normalización de texto en español (dominio).

La usan la percepción del mensaje, la detección de documentos, la búsqueda por palabras y la
validación de respuestas. Está en el dominio porque define cómo se "lee" un texto del vecino.
"""
import re
import unicodedata


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes: "Circulación" y "circulacion" quedan iguales."""
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


STOPWORDS = set("""a al algo como con cual cuales cuando de del donde el ella en entre es esa ese esta este
estos fue ha han hasta hay la las le les lo los mas me mi mis muy no nos o para pero por que se si sin sobre
su sus tambien te tengo tiene un una uno unos y ya yo quiero necesito puedo debo cuanto cuanta""".split())


def tokenizar(texto: str) -> list[str]:
    """Tokens para la búsqueda por palabras: sin tildes, sin palabras vacías y con un recorte simple
    a 6 letras ("renovacion" y "renovar" comparten "renova")."""
    palabras = re.findall(r"[a-z0-9]+", normalizar(texto))
    return [p[:6] for p in palabras if p not in STOPWORDS and len(p) > 1]
