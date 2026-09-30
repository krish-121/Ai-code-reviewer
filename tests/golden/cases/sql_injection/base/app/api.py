from flask import Flask, request

from app import db

app = Flask(__name__)


@app.get("/user")
def user():
    return dict(db.find_user(request.args["email"]) or {})
