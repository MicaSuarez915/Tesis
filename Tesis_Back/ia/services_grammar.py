# ia/services_grammar.py
import os, json, tempfile, sys
from typing import List, Dict
from django.conf import settings

from .gpt_client import chat  # misma lib que ya usás para GPT/Azure

def _get_correction_prompt(text: str) -> str:
    """Un prompt ultra-simple que solo pide una cosa: el texto corregido."""
    return (
        "Eres un corrector experto en gramática y ortografía del español. "
        "Tu única tarea es corregir el siguiente texto. Aplica todas las reglas de puntuación, acentuación, espaciado y eufonía. "
        "NO cambies el estilo ni reformules oraciones válidas. "
        "Devuelve ÚNICAMENTE el texto corregido, sin explicaciones ni texto adicional.\n\n"
        f"TEXTO A CORREGIR:\n---\n{text}\n---"
    )

def _get_issues_prompt(original_text: str, corrected_text: str) -> str:
    """Prompt para la SEGUNDA llamada: encontrar las diferencias."""
    return (
        "Eres un auditor que compara dos versiones de un texto. "
        "Analiza el TEXTO ORIGINAL y el TEXTO CORREGIDO y genera una lista en formato JSON de los cambios realizados.\n\n"
        "RESPONDE ÚNICAMENTE CON UN OBJETO JSON que contenga una clave `issues`. "
        "Cada objeto en la lista `issues` debe tener: 'original', 'corrected', 'category' y 'explanation'.\n"
        "Si no hay diferencias, devuelve `{\"issues\": []}`.\n\n"
        f"TEXTO ORIGINAL:\n---\n{original_text}\n---\n\n"
        f"TEXTO CORREGIDO:\n---\n{corrected_text}\n---"
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

# ---------- Orquestador ----------

def grammar_check_from_text_or_file(*, text: str | None = None, file_path: str | None = None, idioma="es", max_issues=200):
    # 1. Extraer páginas (esto no cambia)
    if text:
        pages = _extract_from_text(text); doc_type = "text"
    elif file_path:
        kind = _guess_type_from_path(file_path)
        if kind == "pdf":
            pages = _extract_from_pdf_path(file_path); doc_type = "pdf"
        elif kind == "txt":
            pages = _extract_from_txt_path(file_path); doc_type = "txt"
        elif kind == "docx":
            pages = _extract_from_docx_path(file_path); doc_type = "docx"
        else:
            raise ValueError("Formato no soportado. Usa PDF, TXT o DOCX.")
    else:
        raise ValueError("Debe proveerse 'text' o 'file_path'.")

    all_issues = []
    corrected_pages_text = []
    truncated = False
    
    for pg in pages:
        page_num = pg["page"]
        original_lines = pg["lines"]
        if not original_lines:
            continue
            
        original_text_block = "\n".join(original_lines)

        # --- LLAMADA 1: OBTENER EL TEXTO CORREGIDO (CON EL SYSTEM MESSAGE CORRECTO) ---
        correction_prompt = _get_correction_prompt(original_text_block)
        corrected_text = chat(
            model=settings.GPT_GRAMMAR_MODEL,
            # AÑADIMOS EL MENSAJE DE SISTEMA EXPLÍCITO
            messages=[
                {"role": "system", "content": "Eres un corrector experto que solo devuelve el texto corregido."},
                {"role": "user", "content": correction_prompt}
            ],
            temperature=0.0,
            max_tokens=getattr(settings, "GRAMMAR_MAX_TOKENS", 1500) # Un poco más de espacio
        ).strip()
        
        # --- PASO DE SEGURIDAD ---
        # Si la IA falla y devuelve un texto vacío, usamos el original para no perder datos.
        if not corrected_text:
            corrected_text = original_text_block
            
        corrected_pages_text.append(corrected_text)

        # --- LLAMADA 2: OBTENER LA LISTA DE ERRORES (YA FUNCIONABA BIEN) ---
        issues_prompt = _get_issues_prompt(original_text_block, corrected_text)
        res_issues = _call_gpt_json(issues_prompt, max_tokens=getattr(settings, "GRAMMAR_MAX_TOKENS", 800))
        
        issues_from_model = res_issues.get("issues", [])
        for issue in issues_from_model:
            issue['page'] = page_num
        all_issues.extend(issues_from_model)

    # 3. Reconstruir la respuesta final
    final_corrected_text = "\n\n".join(corrected_pages_text)
    limited_issues = all_issues[:max_issues]
    
    counts_by_page = {}
    for it in limited_issues:
        page_str = str(it.get("page", 1))
        counts_by_page[page_str] = counts_by_page.get(page_str, 0) + 1

    return {
        "issues": limited_issues,
        "counts": {"total": len(limited_issues), "por_pagina": counts_by_page},
        "meta": {"doc_type": doc_type, "pages": len(pages), "truncated": truncated},
        "corrected_text": final_corrected_text,
    }