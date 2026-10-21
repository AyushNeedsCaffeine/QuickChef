import pytest

from app.services.cart import CartService
from app.services.catalog import get_catalog


@pytest.fixture
def cart():
    return CartService(get_catalog())


def test_add_and_get_cart(cart):
    cart.add_product("s1", "onion", 1)
    cart.add_product("s1", "tomato", 2)
    items = cart.get_cart("s1")
    assert len(items) == 2


def test_merge_same_product(cart):
    cart.add_product("s1", "onion", 1)
    cart.add_product("s1", "onion", 2)
    items = cart.get_cart("s1")
    assert len(items) == 1
    assert items[0].quantity == 3


def test_update_quantity(cart):
    cart.add_product("s1", "onion", 1)
    cart.update_quantity("s1", "onion", 5)
    assert cart.get_cart("s1")[0].quantity == 5


def test_remove_item(cart):
    cart.add_product("s1", "onion", 1)
    cart.update_quantity("s1", "onion", 0)
    assert cart.get_cart("s1") == []


def test_totals(cart):
    cart.add_product("s1", "urad_dal", 1)
    totals = cart.totals("s1")
    assert totals["subtotal"] == 95.0
    assert totals["total"] >= totals["subtotal"]


def test_free_delivery_above_threshold(cart):
    cart.add_product("s1", "cashew", 1)
    totals = cart.totals("s1")
    assert totals["subtotal"] >= 199
    assert totals["delivery_fee"] == 0


def test_place_order_clears_cart(cart):
    cart.add_product("s1", "onion", 1)
    order = cart.place_order("s1")
    assert order.order_id.startswith("QC")
    assert cart.get_cart("s1") == []
    assert len(cart.session_orders("s1")) == 1


def test_place_empty_order_raises(cart):
    with pytest.raises(ValueError):
        cart.place_order("empty")


def test_unknown_product_raises(cart):
    with pytest.raises(ValueError):
        cart.add_product("s1", "nope", 1)
