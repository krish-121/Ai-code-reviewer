from flask import Flask, abort, jsonify, request

from app import auth, db
from app.orders import OrderService

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
