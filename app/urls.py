from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import  UploadFileView, AnalyzeFileView

router = DefaultRouter()

# URL patterns
urlpatterns = [

    #Custom APIView URLs (for the PDF logic)
    path('upload/', UploadFileView.as_view(), name='upload-file'),
    path('analyze/', AnalyzeFileView.as_view(), name='analyze-file'),
]