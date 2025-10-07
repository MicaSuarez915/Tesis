# ia/services_grammar.py
import os, json, tempfile, sys
from typing import List, Dict
from django.conf import settings

from .gpt_client import chat  # misma lib que ya usás para GPT/Azure

def _prompt_for_page(page_num: int, lines: List[str], idioma="es") -> str:
    numbered = "\n".join(f"{i+1}: {ln}" for i, ln in enumerate(lines))
    rules = (
        "Eres un CORRECTOR EXPERTO en GRAMÁTICA, ORTOGRAFÍA y EUFONÍA del español jurídico y formal. "
        "Tu tarea es analizar CADA LÍNEA numerada y detectar SOLO los errores normativos REALES, "
        "según las reglas de la Real Academia Española. NO reescribas el estilo ni reformules el contenido.\n\n"

        "Debes reportar exclusivamente errores de:\n"
        "- Ortografía (acentos, uso incorrecto de mayúsculas/minúsculas, confusión de grafías, etc.).\n"
        "- Gramática (concordancia, uso incorrecto de tiempos verbales, preposiciones, dequeísmo/queísmo, leísmo, laísmo, loísmo, etc.).\n"
        "- Puntuación (signos omitidos o mal ubicados que afecten la estructura sintáctica o el sentido).\n"
        "- Eufonía (uso correcto de 'y/e' y 'o/u' según el sonido inicial de la palabra siguiente).\n\n"

        "APLICA OBLIGATORIAMENTE ESTAS REGLAS DE EUFONÍA:\n"
        "- La conjunción 'y' cambia a 'e' ANTE palabras que comienzan con sonido /i/ "
        "(letra inicial 'i' o 'hi-'). Ejemplos correctos: 'hablamos e iniciamos', 'padres e hijos'. "
        "EXCEPCIÓN: si la palabra comienza con 'hie-', se mantiene 'y' ('y hierro', 'y hiena').\n"
        "- La conjunción 'o' cambia a 'u' ANTE palabras que comienzan con sonido /o/ "
        "(letra inicial 'o' u 'ho-'). Ejemplos correctos: '7 u 8', 'u hoja'. "
        "EXCEPCIÓN: palabras que comienzan con 'hue-' no cambian ('o huevo').\n\n"

        "Instrucciones adicionales:\n"
        "- No hagas cambios de estilo, tono o sintaxis si la redacción es válida.\n"
        "- No modifiques números de expediente, nombres propios ni citas textuales, salvo por tildes evidentes.\n"
        "- No agregues ni elimines contenido; solo corrige lo estrictamente necesario.\n"
        "- Ignora errores tipográficos menores que no alteren la comprensión si no violan normas ortográficas.\n\n"
        "- Agregar o quitar comas o punto y coma **únicamente cuando la norma lo exige**, "
        "por ejemplo para separar oraciones independientes, incisos explicativos o enumeraciones.\n"
        "- Insertar punto final si falta al final de una oración completa.\n"
        "- NO agregues signos de exclamación, interrogación ni cambies el tono.\n"
        "- NO reformules frases ni elimines contenido.\n\n"

        "Por cada error, responde SOLO en JSON con objetos que incluyan SIEMPRE:\n"
        '  - "page": <int>\n'
        '  - "line": <int>\n'
        '  - "original": "<fragmento exacto con error>"\n'
        '  - "corrected": "<fragmento corregido>"\n'
        '  - "original_line": "<TEXTO COMPLETO de la línea antes de cualquier corrección>"\n'
        '  - "corrected_line": "<TEXTO COMPLETO de la línea TRAS aplicar esta corrección>"\n'
        '  - "category": "ortografia|gramatica|puntuacion|eufonia"\n'
        '  - "explanation": "breve regla aplicada"\n\n'
        "IMPORTANTE:\n"
        "- 'corrected_line' DEBE contener la línea completa tras la corrección (no solo el fragmento).\n"
        "- Si no hay errores en una línea, no la reportes.\n"
        'Si no hay problemas en la página, responde {"issues": []}.\n'

    )
    return (
        f"{rules}\n\n"
        f"Página {page_num}. Líneas numeradas:\n{numbered}\n\n"
        "Responde SOLO con JSON. Nada fuera del objeto JSON."
    )

def _call_gpt_json(prompt: str, max_tokens: int) -> Dict:
    raw = chat(
        model=settings.GPT_GRAMMAR_MODEL,
        messages=[{"role": "system", "content": "Eres un riguroso corrector de textos."},
                  {"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=max_tokens
    )
    try:
        return json.loads(raw)
    except Exception:
        return {"issues":[{"page":0,"line":0,"original":"","corrected":"","category":"parser_error","explanation":raw[:800]}]}

# ---------- Extractores de líneas ----------
def _extract_from_txt_path(path:str):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    lines = text.splitlines()
    return [{"page": 1, "lines": lines, "type": "txt"}]

def _extract_from_text(text:str):
    return [{"page": 1, "lines": text.splitlines(), "type": "text"}]

def _extract_from_pdf_path(path:str):
    import fitz  # PyMuPDF
    doc = fitz.open(path)
    pages = []
    for p in range(doc.page_count):
        d = doc[p].get_text("dict")
        lines = []
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                txt = "".join(s.get("text","") for s in spans).strip()
                if txt:
                    lines.append(txt)
        pages.append({"page": p+1, "lines": lines, "type": "pdf"})
    return pages

def _extract_from_docx_path(path:str):
    """
    Intenta convertir a PDF para obtener páginas reales. Si falla, cae a 'una sola página' con líneas.
    """
    # 1) intentar docx2pdf (Windows/Mac con Word)
    pdf_tmp = None
    try:
        from docx2pdf import convert
        import uuid, os
        pdf_tmp = os.path.join(tempfile.gettempdir(), f"tmp_{uuid.uuid4().hex}.pdf")
        convert(path, pdf_tmp)  # puede fallar si no hay Word
        return _extract_from_pdf_path(pdf_tmp)
    except Exception:
        pass
    finally:
        if pdf_tmp and os.path.exists(pdf_tmp):
            try: os.remove(pdf_tmp)
            except Exception: pass

    # 2) fallback: sin páginas reales, 1 página
    from docx import Document
    doc = Document(path)
    lines = []
    for para in doc.paragraphs:
        t = (para.text or "").strip()
        if t:
            lines.extend(t.splitlines())
    return [{"page":1, "lines": lines, "type": "docx_fallback"}]

def _guess_type_from_path(path:str):
    lower = path.lower()
    if lower.endswith(".pdf"): return "pdf"
    if lower.endswith(".txt"): return "txt"
    if lower.endswith(".docx"): return "docx"
    return "unknown"


import re

# 2+ espacios (también captura tabs y no-break spaces)
_SPACES_RUN = re.compile(r'(?:[ \t\u00A0]){2,}')

def _scan_spacing(page_num: int, lines: list[str]) -> list[dict]:
    """
    Detecta líneas con 2+ espacios consecutivos y propone la corrección.
    Devuelve una issue por línea (corrige todos los grupos de espacios de esa línea).
    """
    issues = []
    for idx, line in enumerate(lines, start=1):
        if _SPACES_RUN.search(line):
            corrected = _SPACES_RUN.sub(' ', line)
            issues.append({
                "page": page_num,
                "line": idx,
                "original": line,
                "corrected": corrected,
                "category": "espaciado",
                "explanation": "Se encontraron dos o más espacios consecutivos; se normalizaron a un solo espacio."
            })
    return issues



# ---------- Orquestador ----------
import difflib

def _apply_line_corrections(original_lines: list[str], issues: list[dict]) -> tuple[list[str], list[dict]]:
    """
    Aplica correcciones línea por línea de forma robusta:
      1) Si el issue trae 'corrected_line', se usa esa línea completa.
      2) Si no, intenta reemplazar 'original' -> 'corrected' como FRAGMENTO dentro de la línea.
      3) Si 'corrected' parece un fragmento (muy corto vs. toda la línea) y no hay 'corrected_line',
         NO sustituye toda la línea (evita perder texto); solo intenta reemplazo localizado.
    Devuelve (new_lines, applied_issues).
    """
    new_lines = original_lines[:]
    applied: list[dict] = []

    # Agrupamos issues por línea y respetamos el orden de llegada
    issues_by_line: dict[int, list[dict]] = {}
    for it in issues or []:
        try:
            ln = int(it.get("line", 0))
        except Exception:
            continue
        if not (1 <= ln <= len(original_lines)):
            continue
        issues_by_line.setdefault(ln, []).append(it)

    for ln, line_issues in issues_by_line.items():
        current = new_lines[ln - 1]
        changed = False

        for it in line_issues:
            orig_frag = it.get("original") or ""
            corr_frag = it.get("corrected") or ""
            corr_full = it.get("corrected_line")

            # (1) Preferimos la línea completa si viene provista
            if isinstance(corr_full, str) and corr_full and corr_full != current:
                prior = current
                current = corr_full
                applied.append({
                    "page": it.get("page"),
                    "line": ln,
                    "original": prior,
                    "corrected": current,
                    "category": it.get("category", "gramatica"),
                    "explanation": it.get("explanation", ""),
                })
                changed = True
                continue

            # (2) Si no viene corrected_line, probamos reemplazo localizado
            if isinstance(orig_frag, str) and orig_frag and isinstance(corr_frag, str):
                if orig_frag in current:
                    prior = current
                    current = current.replace(orig_frag, corr_frag, 1)  # primera ocurrencia
                    if current != prior:
                        applied.append({
                            "page": it.get("page"),
                            "line": ln,
                            "original": prior,
                            "corrected": current,
                            "category": it.get("category", "gramatica"),
                            "explanation": it.get("explanation", ""),
                        })
                        changed = True
                        continue

            # (3) Último recurso: si el modelo intentó devolver “toda la línea” en 'corrected'
            # y es MUY similar a la actual (ratio alto), aceptamos (evita colapsos a un fragmento).
            if isinstance(corr_frag, str) and corr_frag:
                ratio = difflib.SequenceMatcher(a=current, b=corr_frag).ratio()
                if ratio > 0.75 and corr_frag != current:
                    prior = current
                    current = corr_frag
                    applied.append({
                        "page": it.get("page"),
                        "line": ln,
                        "original": prior,
                        "corrected": current,
                        "category": it.get("category", "gramatica"),
                        "explanation": it.get("explanation", ""),
                    })
                    changed = True
                    continue

            # Si nada aplica, no tocamos la línea
            # (evita el caso 'sí o sí' reemplazando todo)
        
        if changed:
            new_lines[ln - 1] = current

    return new_lines, applied



def grammar_check_from_text_or_file(*, text: str | None = None, file_path: str | None = None, idioma="es", max_issues=200):
    # 1) extraer líneas por página
    if text:
        pages = _extract_from_text(text)
        doc_type = "text"
    elif file_path:
        kind = _guess_type_from_path(file_path)
        if kind == "pdf":
            pages = _extract_from_pdf_path(file_path); doc_type = "pdf"
        elif kind == "txt":
            pages = _extract_from_txt_path(file_path); doc_type = "txt"
        elif kind == "docx":
            pages = _extract_from_docx_path(file_path); doc_type = "docx/pdf_fallback"
        else:
            raise ValueError("Formato no soportado. Usa PDF, TXT o DOCX.")
    else:
        raise ValueError("Debe proveerse 'text' o 'file_path'.")

    # 2) procesar por página (prompts más chicos)
    all_issues = []
    truncated = False
    max_lines = getattr(settings, "GRAMMAR_MAX_LINES_PER_PAGE", 400)

    # para reconstruir el texto corregido
    corrected_pages = []  # [{'page': n, 'lines': [...]}]

    for pg in pages:
        page_num = pg["page"]
        lines_full = pg["lines"]
        lines = lines_full[:max_lines]
        if len(lines_full) > max_lines:
            truncated = True
        if not lines:
            corrected_pages.append({"page": page_num, "lines": []})
            continue

        # ---- (A) GRAMÁTICA/ORTOGRAFÍA con LLM ----
        prompt = _prompt_for_page(page_num, lines, idioma=idioma)
        res = _call_gpt_json(prompt, max_tokens=getattr(settings, "GRAMMAR_MAX_TOKENS", 800))
        issues_model = res.get("issues", []) or []

        # Aplicar las correcciones de gramática/ortografía línea a línea
        lines_after_grammar, applied_grammar_issues = _apply_line_corrections(lines, issues_model)

        # ---- (B) ESPACIADO sobre el texto YA corregido ----
        spacing_issues = _scan_spacing(page_num, lines_after_grammar)

        # Aplicar también las correcciones de espaciado a las líneas resultantes
        # (reutilizamos _apply_line_corrections, que reemplaza por 'corrected' de cada issue)
        lines_after_spacing, applied_spacing_issues = _apply_line_corrections(lines_after_grammar, spacing_issues)

        # ---- (C) Fusionar issues (sin duplicados) y acumular ----
        seen = set()
        merged = []

        def _try_add(it):
            ln = int(it.get("line", 0))
            if not (1 <= ln <= len(lines)):  # referencia al subconjunto de esta página
                return
            key = (page_num, ln, it.get("corrected", ""))
            if key in seen:
                return
            seen.add(key)
            merged.append({
                "page": page_num,
                "line": ln,
                "original": it.get("original", ""),
                "corrected": it.get("corrected", ""),
                "category": it.get("category", "gramatica"),
                "explanation": it.get("explanation", ""),
            })

        # Primero las de gramática/ortografía, luego espaciado (orden deseado)
        for it in applied_grammar_issues:
            _try_add(it)
        for it in applied_spacing_issues:
            _try_add(it)

        all_issues.extend(merged)

        # guardar líneas corregidas finales de la página
        corrected_pages.append({"page": page_num, "lines": lines_after_spacing})

        if len(all_issues) >= max_issues:
            truncated = True
            break

    # 3) conteos
    limited = all_issues[:max_issues]
    counts_by_page = {}
    for it in limited:
        counts_by_page[str(it["page"])] = counts_by_page.get(str(it["page"]), 0) + 1

    # 4) reconstruir el texto completo corregido (con salto de página como doble salto de línea)
    corrected_text = []
    for p in sorted(corrected_pages, key=lambda x: x["page"]):
        corrected_text.extend(p["lines"])
        corrected_text.append("")  # separador de página
    corrected_text = "\n".join(corrected_text).rstrip()

    return {
        "issues": limited,
        "counts": {"total": len(limited), "por_pagina": counts_by_page},
        "meta": {"doc_type": doc_type, "pages": len(pages), "truncated": truncated},
        "corrected": {
            "pages": corrected_pages,      # lista por página con líneas corregidas
            "text": corrected_text,        # documento completo corregido
        },
    }

