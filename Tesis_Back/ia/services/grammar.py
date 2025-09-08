# ia/services/grammar.py
from typing import Dict, Any, List, Tuple
import language_tool_python as lt
from django.conf import settings

# Instancia única del checker (mejora performance)
_TOOL = None

def _get_tool() -> lt.LanguageTool:
    global _TOOL
    if _TOOL is None:
        _TOOL = lt.LanguageTool(settings.LT_LANG)  # "es-AR" o "es-ES"
    return _TOOL

def grammar_check(text: str) -> Dict[str, Any]:
    """
    Corrección ortográfica y gramatical con LanguageTool.
    Devuelve el texto corregido y la lista de issues detectados.
    """
    tool = _get_tool()
    matches = tool.check(text)
    corrected = lt.utils.correct(text, matches)

    issues: List[Dict[str, Any]] = []
    for m in matches:
        issues.append({
            "message": m.message,
            "replacements": [r.value for r in m.replacements][:5],
            "offset": m.offset,
            "length": m.errorLength,
            "ruleId": m.ruleId,
            "context": m.context,
        })

    return {"corrected": corrected, "issues": issues}
# Ejemplo de uso:
# result = grammar_check("Este es un texto con errores.")