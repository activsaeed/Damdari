from decimal import Decimal
from sqlalchemy import event
from app.extensions import db


@event.listens_for(db.session, "before_flush")
def observe_transaction_deletion(session, flush_context, instances):
    for obj in session.deleted:
        if isinstance(obj, Transaction) and obj.category == 'خرید انبار (خودکار)':
            amount = obj.inventory_quantity
            item = InventoryItem.query.get(obj.inventory_item_id) if obj.inventory_item_id else None
            if not item and amount is None:
                import re
                match = re.search(r"خرید ([\d.]+) .* (.*)$", obj.description)
                if match:
                    amount = Decimal(match.group(1))
                    item = InventoryItem.query.filter_by(name=match.group(2).strip()).first()
            if item and amount:
                try:
                    if item.quantity >= amount:
                        item.quantity -= amount
                    else:
                        raise Exception(f"خطای حسابرسی: حذف این فاکتور باعث منفی شدن موجودی {item.name} می‌شود.")
                except Exception as e:
                    if "خطای حسابرسی" in str(e):
                        raise e


# Import models at module level for the listener
from app.models import Transaction, InventoryItem