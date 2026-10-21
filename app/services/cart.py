from __future__ import annotations

import uuid

from app import config
from app.models import CartItem, Order
from app.services.catalog import Catalog, get_catalog


class CartService:
    def __init__(self, catalog: Catalog | None = None):
        self.catalog = catalog or get_catalog()
        self._carts: dict[str, dict[str, CartItem]] = {}
        self._orders: dict[str, Order] = {}
        self._session_orders: dict[str, list[str]] = {}

    def get_cart(self, session_id: str) -> list[CartItem]:
        return list(self._carts.get(session_id, {}).values())

    def clear(self, session_id: str) -> None:
        self._carts[session_id] = {}

    def add_items(self, session_id: str, items: list[CartItem]) -> list[CartItem]:
        cart = self._carts.setdefault(session_id, {})
        for item in items:
            key = f"{item.product_id}:{item.pack_size}{item.pack_unit}"
            if key in cart:
                cart[key].quantity += item.quantity
            else:
                cart[key] = item
        return list(cart.values())

    def add_product(self, session_id: str, product_id: str, quantity: int = 1) -> CartItem:
        product = self.catalog.get(product_id)
        if product is None:
            raise ValueError(f"Unknown product: {product_id}")
        pack = min(product.packs, key=lambda p: p.price)
        size_str = str(int(pack.size)) if float(pack.size).is_integer() else str(pack.size)
        item = CartItem(
            product_id=product.id,
            name=f"{product.name} ({size_str}{pack.unit})",
            pack_size=pack.size,
            pack_unit=pack.unit,
            quantity=max(1, quantity),
            unit_price=pack.price,
        )
        return self.add_items(session_id, [item])[-1]

    def update_quantity(self, session_id: str, product_id: str, quantity: int) -> list[CartItem]:
        cart = self._carts.get(session_id, {})
        for key, item in list(cart.items()):
            if item.product_id == product_id:
                if quantity <= 0:
                    del cart[key]
                else:
                    item.quantity = quantity
                break
        return list(cart.values())

    def remove_product(self, session_id: str, product_id: str) -> list[CartItem]:
        return self.update_quantity(session_id, product_id, 0)

    def totals(self, session_id: str) -> dict[str, float]:
        items = self.get_cart(session_id)
        subtotal = round(sum(i.line_total for i in items), 2)
        delivery = 0.0 if subtotal >= config.FREE_DELIVERY_ABOVE or subtotal == 0 else config.DELIVERY_FEE
        handling = config.HANDLING_FEE if subtotal > 0 else 0.0
        total = round(subtotal + delivery + handling, 2)
        return {
            "subtotal": subtotal,
            "delivery_fee": delivery,
            "handling_fee": handling,
            "total": total,
        }

    def place_order(self, session_id: str, address: str = "Home", payment_method: str = "cod") -> Order:
        items = self.get_cart(session_id)
        if not items:
            raise ValueError("Cart is empty")
        totals = self.totals(session_id)
        order = Order(
            order_id="QC" + uuid.uuid4().hex[:8].upper(),
            items=items,
            subtotal=totals["subtotal"],
            delivery_fee=totals["delivery_fee"],
            handling_fee=totals["handling_fee"],
            total=totals["total"],
            status="placed",
            payment_method=payment_method,
            address=address,
        )
        self._orders[order.order_id] = order
        self._session_orders.setdefault(session_id, []).append(order.order_id)
        self.clear(session_id)
        return order

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def session_orders(self, session_id: str) -> list[Order]:
        return [self._orders[oid] for oid in self._session_orders.get(session_id, []) if oid in self._orders]


cart_service = CartService()
