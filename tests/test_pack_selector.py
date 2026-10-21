from app.services import pack_selector
from app.services.catalog import get_catalog


def test_unit_conversion_mass():
    assert pack_selector.to_base(1, "kg") == (1000.0, "mass")
    assert pack_selector.to_base(500, "g") == (500.0, "mass")


def test_unit_conversion_volume():
    assert pack_selector.to_base(1, "cup") == (240.0, "volume")
    assert pack_selector.to_base(2, "tbsp") == (30.0, "volume")


def test_select_single_small_pack():
    catalog = get_catalog()
    butter = catalog.get("butter")
    selections, required = pack_selector.select_packs(butter, 100, "g")
    assert required == 100
    pack, count = selections[0]
    assert count == 1
    assert pack.size == 100


def test_select_multiple_packs_for_large_quantity():
    catalog = get_catalog()
    onion = catalog.get("onion")
    selections, _ = pack_selector.select_packs(onion, 1500, "g")
    pack, count = selections[0]
    assert pack.size * count >= 1500


def test_cheapest_pack_wins():
    catalog = get_catalog()
    onion = catalog.get("onion")
    selections, _ = pack_selector.select_packs(onion, 2000, "g")
    pack, count = selections[0]
    assert pack.size == 1000
    assert count == 2


def test_count_unit_items():
    catalog = get_catalog()
    lemon = catalog.get("lemon")
    selections, _ = pack_selector.select_packs(lemon, 2, "pc")
    pack, count = selections[0]
    assert count == 1
    assert pack.unit == "pc"


def test_build_cart_item_pricing():
    catalog = get_catalog()
    tomato = catalog.get("tomato")
    item = pack_selector.build_cart_item(tomato, 1000, "g")
    assert item is not None
    assert item.line_total == item.unit_price * item.quantity
