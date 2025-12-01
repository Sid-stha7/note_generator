from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PDFUploadAnalyzeViewSet, ProductViewSet

# Create router
router = DefaultRouter()

# Register viewsets
router.register(r'products', ProductViewSet, basename='product')
router.register(r'pdf', PDFUploadAnalyzeViewSet, basename='pdf')

# URL patterns
urlpatterns = [
    path('', include(router.urls)),
]
