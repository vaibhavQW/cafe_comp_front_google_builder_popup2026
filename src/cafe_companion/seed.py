from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Cafe, MenuItem

DEMO_MENU = [
    # name, category, price (rupees), prep min, description, tags
    ("Espresso", "Coffee", 120, 2, "Double shot, house blend, chocolatey finish.", ["strong", "quick", "hot"]),
    ("Cappuccino", "Coffee", 180, 4, "Espresso with velvety steamed milk and foam.", ["milky", "hot", "classic"]),
    ("Café Latte", "Coffee", 190, 4, "Smooth espresso with lots of steamed milk.", ["milky", "hot", "mild"]),
    ("Cold Brew", "Coffee", 220, 1, "Steeped 18 hours. Served over ice.", ["cold", "strong", "quick", "refreshing"]),
    ("Iced Mocha", "Coffee", 240, 4, "Espresso, dark chocolate, milk, ice.", ["cold", "sweet", "chocolate"]),
    ("Masala Chai", "Tea", 110, 5, "Assam tea brewed with ginger, cardamom and spices.", ["hot", "spiced", "comfort"]),
    ("Matcha Latte", "Tea", 230, 4, "Ceremonial matcha whisked with oat milk.", ["green", "calm", "vegan"]),
    ("Butter Croissant", "Bakery", 140, 2, "Flaky, all-butter, baked this morning.", ["quick", "snack", "vegetarian"]),
    ("Chocolate Brownie", "Bakery", 150, 1, "Fudgy dark chocolate brownie.", ["sweet", "chocolate", "quick"]),
    ("Grilled Veg Sandwich", "Sandwiches", 220, 8, "Grilled peppers, onion, cheese and mint chutney.", ["vegetarian", "filling", "hot"]),
    ("Chicken Club Sandwich", "Sandwiches", 280, 10, "Triple-decker with chicken, egg, lettuce, tomato.", ["filling", "protein"]),
    ("Paneer Tikka Sandwich", "Sandwiches", 250, 9, "Smoky paneer tikka, onions, cheese on sourdough.", ["vegetarian", "spicy", "filling"]),
]


def seed(db: Session) -> None:
    if db.scalar(select(Cafe).where(Cafe.slug == "demo")):
        return
    cafe = Cafe(slug="demo", name="Brew & Co.", tagline="Good coffee, good company.", currency="INR", table_count=12)
    db.add(cafe)
    db.flush()
    for i, (name, cat, price, prep, desc, tags) in enumerate(DEMO_MENU):
        db.add(MenuItem(cafe_id=cafe.id, name=name, category=cat, price_cents=price * 100,
                        prep_minutes=prep, description=desc, tags=tags, sort=i))
    db.commit()
