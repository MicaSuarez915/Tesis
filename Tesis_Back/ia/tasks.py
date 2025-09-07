from celery import shared_task
from transformers import pipeline
import language_tool_python
from .models import IALog


@shared_task
def summarize_text(text: str, user_id: int, document_id: int | None = None) -> str:
    """Genera un resumen del texto recibido y lo registra."""
    summarizer = pipeline("summarization", model="facebook/bart-large-cnn")
    summary = summarizer(text, max_length=130, min_length=30, do_sample=False)[0]["summary_text"]
    IALog.objects.create(user_id=user_id, document_id=document_id, task_type=IALog.TASK_SUMMARIZE, result=summary)
    return summary


@shared_task
def grammar_check_text(text: str, user_id: int) -> str:
    """Corrige gramática y estilo del texto recibido y lo registra."""
    tool = language_tool_python.LanguageTool("es")
    matches = tool.check(text)
    corrected = language_tool_python.utils.correct(text, matches)
    IALog.objects.create(user_id=user_id, task_type=IALog.TASK_GRAMMAR, result=corrected)
    return corrected
