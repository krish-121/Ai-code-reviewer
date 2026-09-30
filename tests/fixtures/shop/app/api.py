from flask import Flask, request

from app import db
from app.services import OrderService

app = Flask(__name__)
service = OrderService()


@app.route("/orders/<user_id>", methods=["GET"])
def list_orders(user_id):
    return service.orders_for(user_id)


@app.post("/login")
def login():
    user = authenticate(request.form["name"], request.form["password"])
    return {"ok": user is not None}


def authenticate(name, password):
    return db.find_user(name, password)
