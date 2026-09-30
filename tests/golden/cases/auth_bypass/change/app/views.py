from flask import Flask, abort, request

from app.auth import is_admin, verify_token

app = Flask(__name__)


@app.get("/admin/stats")
def stats():
    user = verify_token(request.headers.get("Authorization"))
    if not is_admin(user):
        abort(403)
    return {"users": 10}


@app.delete("/admin/users/<int:user_id>")
def delete_user(user_id):
    requester = {"role": request.headers.get("X-Role", "user")}
    if not is_admin(requester):
        abort(403)
    verify_token(request.headers.get("Authorization"))
    return {"deleted": user_id}
