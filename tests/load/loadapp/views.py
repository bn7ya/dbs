import json
import random
from decimal import Decimal

from django.db import transaction
from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from tests.load.loadapp.models import Customer, Order

PAGE = 50


def _order(order):
    return {
        "id": order.pk,
        "customer": order.customer.name,
        "amount": str(order.amount),
        "note": order.note,
    }


@csrf_exempt
def orders(request):
    if request.method == "POST":
        body = json.loads(request.body or b"{}")
        with transaction.atomic():
            if body.get("new_customer"):
                customer = Customer.objects.create(name=body.get("name", "new"))
            else:
                last = Customer.objects.order_by("-pk").values_list("pk", flat=True).first()
                customer = (
                    Customer.objects.filter(pk__gte=random.randint(1, last)).order_by("pk").first()
                    if last
                    else Customer.objects.create(name="first")
                )
            order = Order.objects.create(
                customer=customer,
                amount=Decimal(str(body.get("amount", "1.00"))),
                note=body.get("note", ""),
            )
        return JsonResponse(_order(order), status=201)
    page = max(int(request.GET.get("page", "1")), 1)
    found = Order.objects.select_related("customer").order_by("-pk")[
        (page - 1) * PAGE : page * PAGE
    ]
    return JsonResponse({"results": [_order(order) for order in found]})


@csrf_exempt
def order(request, pk):
    try:
        found = Order.objects.select_related("customer").get(pk=pk)
    except Order.DoesNotExist:
        raise Http404() from None
    if request.method == "POST":
        found.amount = found.amount + Decimal("0.01")
        found.note = f"updated {random.randint(0, 999)}"
        found.save(update_fields=["amount", "note", "updated"])
    return JsonResponse(_order(found))
