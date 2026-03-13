"""koffeecart URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.1/topics/http/urls/
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
from . import views
from django.conf.urls.static import static
from django.conf import settings
from django.http import JsonResponse
from django.db import connection

def health_check(request):
    try:
        connection.ensure_connection()
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {str(e)}"

    status = {
        "status": "ok" if db_status == "ok" else "degraded",
        "app": "koffeecart",
        "database": db_status,
    }

    http_status = 200 if status["status"] == "ok" else 503
    return JsonResponse(status, status=http_status)


urlpatterns = [
    #path('admin/', admin.site.urls),
    path('securelogin/', admin.site.urls),
    path('', views.home, name='home'),
    path('store/', include('store.urls')),
    path('cart/', include('carts.urls')),
    path('accounts/', include('accounts.urls')),
    path('health/', health_check, name='health_check'),
    # ORDERS
    path('orders/', include('orders.urls')),
] 
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
