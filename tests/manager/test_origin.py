import pytest
from django.test import RequestFactory

from dbs.manager.middleware import RequestOriginMiddleware, current_ip


def seen_by_a_view(**meta):
    seen = []

    def view(request):
        seen.append(current_ip())

    RequestOriginMiddleware(view)(RequestFactory().get("/api/activity/", **meta))
    return seen[0]


def test_the_address_is_remote_addr():
    assert seen_by_a_view(REMOTE_ADDR="198.51.100.7") == "198.51.100.7"


def test_x_real_ip_is_never_read():
    assert seen_by_a_view(REMOTE_ADDR="198.51.100.7", HTTP_X_REAL_IP="203.0.113.5") == (
        "198.51.100.7"
    )


@pytest.mark.parametrize("address", ["not-an-address", "999.1.1.1", "fe80::1%eth0", ""])
def test_an_address_that_is_not_one_is_none(address):
    assert seen_by_a_view(REMOTE_ADDR=address) is None


def test_the_address_is_cleared_after_the_request():
    seen_by_a_view(REMOTE_ADDR="198.51.100.7")

    assert current_ip() is None


def test_the_address_is_cleared_when_the_view_raises():
    def failing(request):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        RequestOriginMiddleware(failing)(
            RequestFactory().get("/", REMOTE_ADDR="198.51.100.7")
        )

    assert current_ip() is None
