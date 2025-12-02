from django.contrib import admin
from django.urls import path, include
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

from app.views import UploadFileView, AnalyzeFileView  # Your views

# 1. Define the Swagger Info
schema_view = get_schema_view(
    openapi.Info(
        title="PDF Analyzer API",
        default_version='v1',
        description="API to upload and analyze PDFs using Perplexity",
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
  path('upload/', UploadFileView.as_view(), name='upload-file'),
    path('analyze/', AnalyzeFileView.as_view(), name='analyze-file'),

    # Swagger URLs
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
]