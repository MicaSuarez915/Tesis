"""
URL configuration for tesis_api project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework import permissions
from usuarios.views import UsuarioViewSet, RolViewSet, EstudioJuridicoViewSet, EstudioUsuarioViewSet, HealthCheckViewSet
from causa.views import (
    CausaViewSet, ParteViewSet, RolParteViewSet, ProfesionalViewSet, EventoProcesalViewSet, CausaParteViewSet, CausaProfesionalViewSet, DocumentoViewSet, CausaDesdeDocumentoView
)
from ia.views import SummaryRunViewSet, GrammarCheckView, AskJurisView, ConversationDetailView,ConversationMessageCreateView, AsistenteJurisprudencia, ConversationListView
from tasks.views import TaskViewSet
from trazability.views import TrazabilityViewSet



router = DefaultRouter()
router.register(r"usuarios", UsuarioViewSet)
router.register(r"roles", RolViewSet)
router.register(r"estudios", EstudioJuridicoViewSet)
router.register(r"estudios-usuarios", EstudioUsuarioViewSet)
router.register(r"causas", CausaViewSet)
router.register(r"partes", ParteViewSet)
router.register(r"roles-parte", RolParteViewSet)
router.register(r"profesionales", ProfesionalViewSet)
router.register(r"eventos", EventoProcesalViewSet)
router.register(r"causas-partes", CausaParteViewSet)
router.register(r"causas-profesionales", CausaProfesionalViewSet)
router.register(r"health", HealthCheckViewSet, basename="health")
router.register(r"ia/summaries", SummaryRunViewSet, basename="ia-summaries")
router.register(r"documentos", DocumentoViewSet, basename="documentos")
router.register(r'tasks', TaskViewSet, basename='task')
router.register(r'trazability', TrazabilityViewSet, basename='trazability')



urlpatterns = [
    path('admin/', admin.site.urls),
    path(
        'api/causas/crear-desde-documento/', 
        CausaDesdeDocumentoView.as_view(), 
        name='causa-desde-documento'
    ),
    path("api/", include(router.urls)),
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/schema/", SpectacularAPIView.as_view(permission_classes=[permissions.AllowAny]), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema", permission_classes=[permissions.AllowAny])),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema", permission_classes=[permissions.AllowAny])),
   # path("api/ia/causas/<int:causa_id>/summary/", CaseSummaryView.as_view(), name="ia-case-summary"),
    path("api/ia/grammar/check/", GrammarCheckView.as_view(), name="ia-grammar-check"),
    path("api/ia/ask-juris/", AskJurisView.as_view()),
    path("api/conversations/", AsistenteJurisprudencia.as_view(), name="conversations"),
    #path("api/conversations", ConversationsView.as_view(), name="conversations"),
    path("api/conversations", ConversationListView.as_view(), name="conversation-list"),
    path("api/conversations/<str:conversation_id>", ConversationDetailView.as_view(), name="conversation-detail"),
    
]
