from django.contrib import admin
from django.urls import path
from app.views import SimpleAnalyzeView  # Import the view we just made

urlpatterns = [
    path('admin/', admin.site.urls),
    # This creates the endpoint: http://127.0.0.1:8000/analyze/
    path('analyze/', SimpleAnalyzeView.as_view(), name='analyze'),
]