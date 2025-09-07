from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema

from .serializers import (
    SummarizeSerializer,
    SummarizeResponseSerializer,
    GrammarCheckSerializer,
    GrammarCheckResponseSerializer,
)
from .tasks import summarize_text, grammar_check_text


class SummarizeView(APIView):
    """Endpoint para resumir textos o documentos."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=SummarizeSerializer,
        responses=SummarizeResponseSerializer,
        description="Genera un resumen corto del texto enviado.",
    )
    def post(self, request):
        serializer = SummarizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        text = serializer.validated_data.get("text", "")
        uploaded = serializer.validated_data.get("file")
        if uploaded and not text:
            text = uploaded.read().decode("utf-8")
        task = summarize_text.delay(text, request.user.id)
        summary = task.get()
        return Response({"summary": summary})


class GrammarCheckView(APIView):
    """Endpoint para corregir gramática y estilo."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=GrammarCheckSerializer,
        responses=GrammarCheckResponseSerializer,
        description="Devuelve el texto corregido.",
    )
    def post(self, request):
        serializer = GrammarCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        text = serializer.validated_data["text"]
        task = grammar_check_text.delay(text, request.user.id)
        corrected = task.get()
        return Response({"corrected_text": corrected})
