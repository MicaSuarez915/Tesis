from django.urls import path
from .views import SummarizeView, GrammarCheckView

urlpatterns = [
    path("summarize/", SummarizeView.as_view(), name="ia-summarize"),
    path("grammar-check/", GrammarCheckView.as_view(), name="ia-grammar-check"),
]
