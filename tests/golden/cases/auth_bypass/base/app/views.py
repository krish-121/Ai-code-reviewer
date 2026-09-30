from flask import Flask, abort, request

from app.auth import is_admin, verify_token

app = Flask(__name__)


@app.get("/admin/stats")
def stats():
    user = verify_token(request.headers.get("Authorization"))
    if not is_admin(user):
        abort(403)
    return {"users": 10}
