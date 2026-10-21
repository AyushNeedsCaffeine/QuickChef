from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Pack(BaseModel):
    size: float
    unit: Literal["g", "kg", "ml", "l", "pc"]
    price: float
    stock: int = 500


class Product(BaseModel):
    id: str
    name: str
    category: str
    aliases: list[str] = Field(default_factory=list)
    packs: list[Pack]


class Ingredient(BaseModel):
    name: str
    quantity: float
    unit: str
    category: str = "other"


class CartItem(BaseModel):
    product_id: str
    name: str
    pack_size: float
    pack_unit: str
    quantity: int
    unit_price: float

    @property
    def line_total(self) -> float:
        return round(self.unit_price * self.quantity, 2)


class Order(BaseModel):
    order_id: str
    items: list[CartItem]
    subtotal: float
    delivery_fee: float
    handling_fee: float
    total: float
    status: str = "placed"
    payment_method: str = "cod"
    address: str = "Home"


class ChatRequest(BaseModel):
    message: str


class DishRequest(BaseModel):
    dish: str


class ServingsRequest(BaseModel):
    dish: str
    servings: int = Field(ge=1, le=100)


class CartAddRequest(BaseModel):
    product_id: str
    quantity: int = 1


class CartUpdateRequest(BaseModel):
    quantity: int


class SynonymRequest(BaseModel):
    term: str
    canonical: str


class FeedbackRequest(BaseModel):
    kind: Literal["dish_rejected", "dish_correction", "review_liked", "review_disliked"]
    raw: Optional[str] = None
    dish: Optional[str] = None
    display: Optional[str] = None
    candidates: list[dict] = Field(default_factory=list)
    needs_clarification: Optional[bool] = None
    modifiers: Optional[bool] = None
    source: Optional[str] = None
    parent_id: Optional[str] = None
    accepted_raw: Optional[str] = None
    accepted_dish: Optional[str] = None
    accepted_display: Optional[str] = None


class ConfirmRequest(BaseModel):
    address: Optional[str] = "Home"


class PayRequest(BaseModel):
    method: str = "cod"
    address: Optional[str] = "Home"
