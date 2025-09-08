from celery import shared_task
from ia.services import build_causa_context_db, summarize
from ia.services.grammar import grammar_check

@shared_task(bind=True)
def task_grammar_check(self, text: str):
    """
    Devuelve texto corregido + issues detectados por LanguageTool.
    """
    res = grammar_check(text)
    return {
        "corrected_text": res["corrected"],
        "issues": res["issues"],
        "engine": "languagetool-local"
    }



@shared_task
def task_summarize_causa_db(
    causa_id: int,
    max_words: int = 300,
    style: str = "legal-brief",
    include_doc_text_field: bool = False,  # 👈 aceptado
):
    context = build_causa_context_db(
        causa_id,
        include_partes=True,
        include_profesionales=True,
        include_eventos=True,
        include_docs_metadata=True,
        max_chars=30000,
    )
    res = summarize(text=context, max_words=max_words, style=style)
    return {"causa_id": causa_id, "summary": res["summary"], "engine": res["engine"]}
    # hoy no se usa include_doc_text_field, porque Documento.texto no existe
    # pero queda en la firma de la task por si se agrega en el futuro