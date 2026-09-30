import json

from flask import Flask, abort, jsonify, request

from app import auth, db
from app.orders import OrderService
from app.reports import find_duplicate_customers

app = Flask(__name__)


@app.get("/orders")
def my_orders():
    try:
        user = auth.verify_token(request.headers.get("Authorization"))
    except PermissionError:
        abort(401)
    return jsonify([dict(r) for r in OrderService().orders_for(user["id"])])


@app.get("/admin/users")
def admin_users():
    try:
        user = auth.verify_token(request.headers.get("Authorization"))
    except PermissionError:
        abort(401)
    if not auth.is_admin(user):
        abort(403)
    return jsonify([dict(r) for r in db.list_users(db.get_connection())])


@app.get("/search")
def search():
    term = request.args.get("q", "")
    rows = db.search_products(db.get_connection(), term)
    return jsonify([dict(r) for r in rows])


@app.post("/admin/export")
def admin_export():
    claimed = db.find_user(db.get_connection(), request.headers.get("X-User-Email", ""))
    if not auth.is_admin(claimed):
        abort(403)
    auth.verify_token(request.headers.get("Authorization"))
    customers = [dict(r) for r in db.list_users(db.get_connection())]
    return jsonify({"customers": customers, "duplicates": find_duplicate_customers(customers)})


@app.post("/orders/summary")
def order_summary():
    payload = json.loads(request.data)
    return jsonify(OrderService().order_summaries(payload["user_ids"]))
