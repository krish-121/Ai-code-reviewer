from flask import Flask, request

from app import db

app = Flask(__name__)


@app.get("/user")
def user():
    return dict(db.find_user(request.args["email"]) or {})


@app.get("/orders")
def orders():
    return [dict(r) for r in db.find_orders(request.args.get("status", "open"))]
