# ia/services_grammar.py
import os, json, tempfile, sys
from typing import List, Dict
from django.conf import settings

from .gpt_client import chat  # misma lib que ya usás para GPT/Azure

def _prompt_for_page(page_num: int, lines: List[str], idioma="es") -> str:
    numbered = "\n".join(f"{i+1}: {ln}" for i, ln in enumerate(lines))
    rules = (
        "Eres un corrector de GRAMÁTICA y ORTOGRAFÍA en español. "
        "Analiza CADA LÍNEA numerada y reporta SOLO las que tengan error normativo real "
        "(ortografía, tildes, mayúsculas, concordancia, puntuación, dequeísmo/queísmo, leísmo, "
        "y REGLAS EUFÓNICAS). "
        "APLICA OBLIGATORIAMENTE ESTAS REGLAS:\n"
        "- Conjunción 'y' → 'e' ANTE palabras que empiezan con sonido /i/ (letra inicial 'i' o 'hi-'), "
        "p. ej., 'hablamos e iniciamos', 'padres e hijos'. EXCEPCIÓN: si empieza por 'hie-' (p. ej., 'y hierro', 'y hiena').\n"
        "- Conjunción 'o' → 'u' ANTE palabras que empiezan con sonido /o/ (letra inicial 'o' u 'ho-'), "
        "p. ej., '7 u 8', 'u hoja'. EXCEPCIÓN: palabras con 'hue-' ('huevo') no cambian ('o huevo').\n"
        "NO hagas cambios de estilo; solo corrige errores reales. No modifiques números de expediente, "
        "nombres propios o citas textuales salvo tildes evidentes.\n\n"
        "Devuelve SOLO JSON con esta forma exacta:\n"
        '{"issues":[{"page":<int>,"line":<int>,"original":"...","corrected":"...","category":"ortografia|gramatica|puntuacion|eufonia","explanation":"..."}]}\n'
        "Usa exactamente los números de línea provistos. Si no hay problemas, devuelve {'issues':[]}."
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

    # 2) llamar al modelo por página (evita prompts gigantes)
    all_issues = []
    truncated = False
    max_lines = getattr(settings, "GRAMMAR_MAX_LINES_PER_PAGE", 400)

    for pg in pages:
        page_num = pg["page"]
        lines = pg["lines"][:max_lines]
        if len(pg["lines"]) > max_lines:
            truncated = True
        if not lines:
            continue

        prompt = _prompt_for_page(page_num, lines, idioma=idioma)
        res = _call_gpt_json(prompt, max_tokens=settings.GRAMMAR_MAX_TOKENS)
        issues_model = res.get("issues", []) or []

        # --- Guardarraíles deterministas ---
        # (opcional) eufonía (y→e / o→u). Descomenta si lo agregaste:
        # issues_rule_euphony = _scan_euphony(page_num, lines)
        issues_rule_spacing = _scan_spacing(page_num, lines)

        # Fusionar evitando duplicados por (page,line,corrected)
        seen = set()
        merged = []

        def _try_add(it):
            ln = int(it.get("line", 0))
            if not (1 <= ln <= len(lines)):
                return
            key = (int(it.get("page", page_num)) or page_num, ln, it.get("corrected", ""))
            if key in seen:
                return
            seen.add(key)
            merged.append({
                "page": key[0],
                "line": ln,
                "original": it.get("original", ""),
                "corrected": it.get("corrected", ""),
                "category": it.get("category", "gramatica"),
                "explanation": it.get("explanation", ""),
            })

        # Primero lo que devuelve el modelo, luego los guardarraíles
        for it in issues_model:
            _try_add(it)
        # for it in issues_rule_euphony:  # <- descomenta si usás eufonía
        #     _try_add(it)
        for it in issues_rule_spacing:
            _try_add(it)

        all_issues.extend(merged)

        if len(all_issues) >= max_issues:
            truncated = True
            break

    # 3) resumen de conteos (¡fuera del for!)
    counts_by_page = {}
    for it in all_issues:
        counts_by_page[str(it["page"])] = counts_by_page.get(str(it["page"]), 0) + 1

    return {
        "issues": all_issues[:max_issues],
        "counts": {"total": len(all_issues[:max_issues]), "por_pagina": counts_by_page},
        "meta": {"doc_type": doc_type, "pages": len(pages), "truncated": truncated},
    }

