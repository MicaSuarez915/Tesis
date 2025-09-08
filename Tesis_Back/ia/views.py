from django.shortcuts import render

# Create your views here.
    
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings

from ia.serializers import CausaSummaryDBRequestSerializer, CausaSummaryDBResponseSerializer
from ia.tasks import task_summarize_causa_db

class CausaSummaryDBView(APIView):
    def post(self, request, causa_id: int):
        s = CausaSummaryDBRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        payload = s.validated_data

        include_doc_text_field = payload.get("include_doc_text_field", False)  # 👈 default seguro

        async_res = task_summarize_causa_db.delay(
            causa_id=causa_id,
            max_words=payload.get("max_words", 300),
            style=payload.get("style", "legal-brief"),
            include_doc_text_field=include_doc_text_field,  # la task lo acepta (aunque hoy no se usa)
        )

        res = async_res.get(timeout=180)  # estás en modo eager
        return Response(res, status=status.HTTP_200_OK)


from ia.serializers import GrammarCheckRequestSerializer, GrammarCheckResponseSerializer
from ia.tasks import task_grammar_check

class GrammarCheckView(APIView):
    """
    POST /api/ia/grammar-check
    body: { "text": "..." }
    """
    def post(self, request):
        s = GrammarCheckRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        payload = s.validated_data

        async_res = task_grammar_check.delay(text=payload["text"])
        if getattr(settings, "NLP_SYNC_IN_DEV", True):
            res = async_res.get(timeout=120)
            return Response(GrammarCheckResponseSerializer(res).data, status=status.HTTP_200_OK)
        return Response({"task_id": async_res.id}, status=status.HTTP_202_ACCEPTED)