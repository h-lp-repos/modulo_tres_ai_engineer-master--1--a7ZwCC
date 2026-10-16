"""Carga del corpus de políticas de OrbitAir (viene del M2 sin cambios; el corpus es el mismo).

En el M3 se usa para `buscar_politica`: un fragmento por subsección.

El corpus son 3 documentos Markdown en corpus/ (equipaje, tarifas y cambios,
reembolsos y compensaciones), cada uno con una cabecera de metadatos (código,
versión, vigencia) y secciones numeradas con headers `##` / `###`.

Cada subsección (`###`) es un fragmento, y una sección `##` sin subsecciones es
un fragmento entero (en el M2 · C2 esta estrategia "por sección" fue la que ganó).

Ids de fragmento: `{código}#{número de sección}` → "POL-EQ-01#6.3".
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

CORPUS_DIR = Path(__file__).resolve().parents[2] / "corpus"

_META = re.compile(r"^\*\*(?P<clave>[^*]+):\*\*\s*(?P<valor>.+)$")
_HEADER = re.compile(r"^(?P<nivel>#{2,3})\s+(?P<num>\d+(?:\.\d+)?)\.?\s+(?P<titulo>.+)$")


@dataclass
class Documento:
    archivo: str
    codigo: str
    titulo: str
    version: str
    vigente_desde: str
    texto: str


@dataclass
class Seccion:
    num: str        # "6.3"
    titulo: str     # "6.3 Mascotas en cabina"
    ruta: str       # "Política de Equipaje de OrbitAir > 6. Equipaje especial > 6.3 Mascotas en cabina"
    cuerpo: str     # texto de la sección, sin el header


@dataclass
class Fragmento:
    id: str
    doc: str        # código del documento, ej. POL-EQ-01
    seccion: str    # número de sección, ej. "6.3"
    titulo: str     # "6.3 Mascotas en cabina"
    ruta: str       # "Política de Equipaje de OrbitAir > 6. Equipaje especial > 6.3 Mascotas en cabina"
    texto: str      # cuerpo del fragmento, sin el header

    @property
    def texto_para_embedding(self) -> str:
        """Lo que se embeddea: el título de la subsección + su cuerpo."""
        return f"{self.titulo}\n{self.texto}"

    def to_dict(self) -> dict:
        return asdict(self)


def cargar_documentos(directorio: Path = CORPUS_DIR) -> list[Documento]:
    return [leer_documento(path) for path in sorted(directorio.glob("*.md"))]


def leer_documento(path: Path) -> Documento:
    texto = path.read_text(encoding="utf-8")
    titulo = next(l[2:].strip() for l in texto.splitlines() if l.startswith("# "))
    meta = {m["clave"].strip(): m["valor"].strip()
            for l in texto.splitlines() if (m := _META.match(l.strip()))}
    return Documento(path.name, meta["Código de documento"], titulo,
                     meta.get("Versión", ""), meta.get("Vigente desde", ""), texto)


def cuerpo_documento(doc: Documento) -> str:
    """El texto desde la primera sección `##` (sin título ni cabecera de metadatos)."""
    lineas = doc.texto.splitlines()
    inicio = next(i for i, l in enumerate(lineas) if l.startswith("## "))
    return "\n".join(lineas[inicio:]).strip() + "\n"


def secciones(doc: Documento) -> Iterator[Seccion]:
    """Recorre el documento por estructura: una Seccion por `###`, o por `##` sin subsecciones.

    Si una sección `##` tiene texto introductorio antes de su primer `###`, ese
    texto sale como una Seccion propia con el número de la sección (ej. "3").
    """
    h2 = None          # "3. Cambios voluntarios"
    actual = None      # (num, titulo, ruta)
    cuerpo: list[str] = []

    def cerrar():
        texto = "\n".join(cuerpo).strip()
        if actual and texto:
            return Seccion(*actual, texto)

    for linea in doc.texto.splitlines():
        m = _HEADER.match(linea)
        if not m:
            if actual:
                cuerpo.append(linea)
            continue
        if s := cerrar():
            yield s
        cuerpo = []
        num, titulo = m["num"], m["titulo"].strip()
        if m["nivel"] == "##":
            h2 = f"{num}. {titulo}"
            actual = (num, h2, f"{doc.titulo} > {h2}")
        else:
            actual = (num, f"{num} {titulo}", f"{doc.titulo} > {h2} > {num} {titulo}")
    if s := cerrar():
        yield s


def fragmentos_por_subseccion(docs: list[Documento] | None = None) -> list[Fragmento]:
    """C1: un fragmento por Seccion (ver `secciones`)."""
    return [Fragmento(f"{doc.codigo}#{s.num}", doc.codigo, s.num, s.titulo, s.ruta, s.cuerpo)
            for doc in docs or cargar_documentos() for s in secciones(doc)]


def fragmento_por_id(id_: str, fragmentos: list[Fragmento] | None = None) -> Fragmento:
    for f in fragmentos or fragmentos_por_subseccion():
        if f.id == id_:
            return f
    raise KeyError(f"No existe el fragmento {id_}")
