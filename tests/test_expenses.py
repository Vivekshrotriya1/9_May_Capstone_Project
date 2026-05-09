import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime
from bson import ObjectId

OID = ObjectId("507f1f77bcf86cd799439011")

DOC = {
    "_id": OID,
    "title": "Lunch",
    "amount": 150.0,
    "category": "food",
    "description": None,
    "date": datetime(2024, 1, 15),
    "created_at": datetime(2024, 1, 15),
}


def make_db(find_one=DOC, delete_count=1, update_matched=1):
    db = MagicMock()

    # expenses collection
    col = MagicMock()
    col.find_one = AsyncMock(return_value=find_one)
    ir = MagicMock(); ir.inserted_id = OID
    col.insert_one = AsyncMock(return_value=ir)
    ur = MagicMock(); ur.matched_count = update_matched
    col.update_one = AsyncMock(return_value=ur)
    dr = MagicMock(); dr.deleted_count = delete_count
    col.delete_one = AsyncMock(return_value=dr)

    cursor = MagicMock()
    cursor.sort = MagicMock(return_value=cursor)
    async def _aiter():
        for item in [DOC]:
            yield item

        cursor.__aiter__.return_value = _aiter()
    col.find = MagicMock(return_value=cursor)

    db.expenses = col
    db.logs = MagicMock()
    db.logs.insert_one = AsyncMock()
    return db


def patch_db(db):
    return patch("app.routes.get_db", return_value=db)


async def req(path, method="GET", json=None, files=None, db=None):
    _db = db or make_db()
    with patch("app.database.connect_db", new_callable=AsyncMock), \
         patch("app.database.close_db", new_callable=AsyncMock), \
         patch_db(_db):
        from app.main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            fn = getattr(c, method.lower())
            kw = {}
            if json is not None: kw["json"] = json
            if files is not None: kw["files"] = files
            return await fn(path, **kw)


@pytest.mark.asyncio
async def test_root():
    r = await req("/")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_create_expense():
    r = await req("/expenses", "POST", json={"title": "Lunch", "amount": 150.0, "category": "food"})
    assert r.status_code == 201
    assert r.json()["amount"] == 150.0


@pytest.mark.asyncio
async def test_create_invalid_amount():
    r = await req("/expenses", "POST", json={"title": "X", "amount": -1, "category": "food"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_all_expenses():
    r = await req("/expenses")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_get_expense_by_id():
    r = await req(f"/expenses/{OID}")
    assert r.status_code == 200
    assert r.json()["id"] == str(OID)


@pytest.mark.asyncio
async def test_get_expense_not_found():
    r = await req(f"/expenses/{OID}", db=make_db(find_one=None))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_expense_invalid_id():
    r = await req("/expenses/bad-id")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_update_expense():
    updated = {**DOC, "title": "Updated"}
    r = await req(f"/expenses/{OID}", "PUT", json={"title": "Updated"}, db=make_db(find_one=updated))
    assert r.status_code == 200
    assert r.json()["title"] == "Updated"


@pytest.mark.asyncio
async def test_update_not_found():
    r = await req(f"/expenses/{OID}", "PUT", json={"title": "X"}, db=make_db(update_matched=0))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_no_fields():
    r = await req(f"/expenses/{OID}", "PUT", json={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_delete_expense():
    r = await req(f"/expenses/{OID}", "DELETE")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_delete_not_found():
    r = await req(f"/expenses/{OID}", "DELETE", db=make_db(delete_count=0))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_csv_upload_valid():
    csv = b"title,amount,category\nLunch,150,food\nCoffee,80,food\n"
    r = await req("/expenses/upload-csv", "POST", files={"file": ("e.csv", csv, "text/csv")})
    assert r.status_code == 201
    assert r.json()["inserted"] == 2


@pytest.mark.asyncio
async def test_csv_invalid_type():
    r = await req("/expenses/upload-csv", "POST", files={"file": ("f.txt", b"x", "text/plain")})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_csv_missing_columns():
    r = await req("/expenses/upload-csv", "POST", files={"file": ("f.csv", b"name,cost\nA,1\n", "text/csv")})
    assert r.status_code == 400
