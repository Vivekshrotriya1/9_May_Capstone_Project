import csv
import io
from datetime import datetime, timezone
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, UploadFile, File
from app.database import get_db
from app.models import ExpenseCreate, ExpenseUpdate

router = APIRouter()


def to_dict(doc):
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


# ── Create ──────────────────────────────────────────────
@router.post("/expenses", status_code=201)
async def create_expense(data: ExpenseCreate):
    db = get_db()
    doc = data.model_dump()
    doc["date"] = doc["date"] or datetime.now(timezone.utc)
    doc["created_at"] = datetime.now(timezone.utc)
    result = await db.expenses.insert_one(doc)
    created = await db.expenses.find_one({"_id": result.inserted_id})
    await db.logs.insert_one({"action": "create", "expense_id": str(result.inserted_id), "at": datetime.now(timezone.utc)})
    return to_dict(created)


# ── Read All ─────────────────────────────────────────────
@router.get("/expenses")
async def get_expenses():
    db = get_db()
    expenses = []
    async for doc in db.expenses.find().sort("created_at", -1):
        expenses.append(to_dict(doc))
    return expenses


# ── Read One ─────────────────────────────────────────────
@router.get("/expenses/{id}")
async def get_expense(id: str):
    db = get_db()
    try:
        doc = await db.expenses.find_one({"_id": ObjectId(id)})
    except InvalidId:
        raise HTTPException(400, "Invalid ID")
    if not doc:
        raise HTTPException(404, "Expense not found")
    return to_dict(doc)


# ── Update ───────────────────────────────────────────────
@router.put("/expenses/{id}")
async def update_expense(id: str, data: ExpenseUpdate):
    db = get_db()
    try:
        oid = ObjectId(id)
    except InvalidId:
        raise HTTPException(400, "Invalid ID")

    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "No fields to update")

    result = await db.expenses.update_one({"_id": oid}, {"$set": fields})
    if result.matched_count == 0:
        raise HTTPException(404, "Expense not found")

    updated = await db.expenses.find_one({"_id": oid})
    await db.logs.insert_one({"action": "update", "expense_id": id, "at": datetime.now(timezone.utc)})
    return to_dict(updated)


# ── Delete ───────────────────────────────────────────────
@router.delete("/expenses/{id}")
async def delete_expense(id: str):
    db = get_db()
    try:
        oid = ObjectId(id)
    except InvalidId:
        raise HTTPException(400, "Invalid ID")

    result = await db.expenses.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(404, "Expense not found")

    await db.logs.insert_one({"action": "delete", "expense_id": id, "at": datetime.now(timezone.utc)})
    return {"message": "Expense deleted"}


# ── CSV Upload ───────────────────────────────────────────
@router.post("/expenses/upload-csv", status_code=201)
async def upload_csv(file: UploadFile = File(...)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files are allowed")

    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8")))

    required = {"title", "amount", "category"}
    if not required.issubset(set(reader.fieldnames or [])):
        raise HTTPException(400, f"CSV must have columns: {', '.join(required)}")

    db = get_db()
    inserted, errors = 0, []

    for i, row in enumerate(reader, start=2):
        try:
            doc = {
                "title": row["title"].strip(),
                "amount": float(row["amount"].strip()),
                "category": row["category"].strip(),
                "description": row.get("description", "").strip() or None,
                "date": datetime.now(timezone.utc),
                "created_at": datetime.now(timezone.utc),
            }
            await db.expenses.insert_one(doc)
            inserted += 1
        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")

    return {"inserted": inserted, "errors": errors}
