from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ...core.database import get_db
from ... import models
from ...schemas import ProductOut, CartOut, CartItemCreate, CartItemOut, OrderOut, DeliveryOut
from typing import List

router = APIRouter()

# Products
@router.get("/products", response_model=List[ProductOut])
def products(q: str | None = None, db: Session = Depends(get_db)):
    query = db.query(models.Product)
    if q: query = query.filter(models.Product.name.ilike(f"%{q}%"))
    return query.order_by(models.Product.id).all()

@router.get("/products/{product_id}", response_model=ProductOut)
def product(product_id: int, db: Session = Depends(get_db)):
    return db.get(models.Product, product_id)

# Cart
@router.get("/cart", response_model=CartOut)
def get_cart(user_id: int = 1, db: Session = Depends(get_db)):
    cart = db.query(models.Cart).filter(models.Cart.user_id==user_id).first()
    if not cart:
        cart = models.Cart(user_id=user_id); db.add(cart); db.commit(); db.refresh(cart)
    return cart

@router.get("/cart/items", response_model=List[CartItemOut])
def cart_items(cart_id: int, db: Session = Depends(get_db)):
    return db.query(models.CartItem).filter(models.CartItem.cart_id==cart_id).all()

@router.post("/cart/items", response_model=CartItemOut)
def add_item(body: CartItemCreate, db: Session = Depends(get_db)):
    item = models.CartItem(**body.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return item

@router.patch("/cart/items/{item_id}", response_model=CartItemOut)
def update_item(item_id: int, qty: int, db: Session = Depends(get_db)):
    item = db.get(models.CartItem, item_id)
    if not item: raise HTTPException(404, "Item not found")
    item.qty = qty; db.commit(); db.refresh(item); return item

@router.delete("/cart/items/{item_id}")
def remove_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(models.CartItem, item_id)
    if not item: raise HTTPException(404, "Item not found")
    db.delete(item); db.commit(); return {"ok": True}

# Orders
@router.get("/orders", response_model=List[OrderOut])
def list_orders(user_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(models.Order)
    if user_id: q = q.filter(models.Order.user_id == user_id)
    return q.order_by(models.Order.id.desc()).all()

@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: Session = Depends(get_db)):
    return db.get(models.Order, order_id)

@router.post("/orders", response_model=OrderOut)
def create_order(user_id: int, cart_id: int, amount: float, db: Session = Depends(get_db)):
    order = models.Order(user_id=user_id, status="created", amount=amount)
    db.add(order); db.commit(); db.refresh(order); return order

# Deliveries
@router.get("/deliveries", response_model=List[DeliveryOut])
def list_deliveries(order_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(models.Delivery)
    if order_id: q = q.filter(models.Delivery.order_id == order_id)
    return q.order_by(models.Delivery.id.desc()).all()

# Rewards
@router.get("/rewards")
def rewards(user_id: int = 1, db: Session = Depends(get_db)):
    total = db.execute("select coalesce(sum(delta),0) as pts from rewards_ledger where user_id=:u", {"u": user_id}).scalar() or 0
    return {"points": int(total)}

@router.get("/rewards/history")
def rewards_history(user_id: int = 1, db: Session = Depends(get_db)):
    items = db.execute("select id, delta, reason from rewards_ledger where user_id=:u order by id desc", {"u": user_id}).mappings().all()
    return list(items)

@router.post("/rewards/redeem")
def redeem(user_id: int = 1, reward_id: str = "sample", db: Session = Depends(get_db)):
    db.execute("insert into rewards_ledger(user_id, delta, reason) values (:u, :d, :r)", {"u": user_id, "d": -100, "r": f"Redeemed {reward_id}"})
    db.commit(); return {"ok": True}
