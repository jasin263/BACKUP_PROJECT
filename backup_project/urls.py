from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('backup_app.urls')),  # Include app URLs
    path('favicon.ico', RedirectView.as_view(url='/static/favicon.ico')),  # Favicon URL
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)