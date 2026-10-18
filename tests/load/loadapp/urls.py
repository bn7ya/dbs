from django.urls import path

from tests.load.loadapp.views import order, orders

urlpatterns = [
    path("orders/", orders),
    path("orders/<int:pk>/", order),
]
