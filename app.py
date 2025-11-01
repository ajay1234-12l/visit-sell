# Main app logic will go here
# app.py
import os, threading, time, httpx, json
from datetime import datetime, timedelta
from typing import Dict, Any
from flask import Flask, request, jsonify, render_template, send_file, redirect, url_for
from flask_cors import CORS
from passlib.context import CryptContext
from jose import jwt

import config
from database import read, write, next_id

if os.environ.get("VERCEL"):
    TMP = "/tmp"
    for k,v in config.CFG["FILES"].items():
        base = os.path.basename(v)
        config.CFG["FILES"][k] = os.path.join(TMP, base)

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)
app.secret_key = config.CFG["SECRET_KEY"]

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGO = "HS256"

# ensure default files exist
read("users", [])
read("tasks", [])
read("redeems", [])
read("audit", [])
read("settings", config.CFG)

# runtime
TASK_THREADS: Dict[int, threading.Thread] = {}
TASK_PROGRESS: Dict[int, Dict[str, Any]] = {}
STOP_FLAGS: Dict[int, bool] = {}
GLOBAL_LOCK = threading.Lock()

def now_iso():
    return datetime.utcnow().isoformat()

def create_token(user_id: int) -> str:
    exp = datetime.utcnow() + timedelta(days=int(config.CFG.get("JWT_EXPIRE_DAYS", 7)))
    payload = {"sub": str(user_id), "exp": int(exp.timestamp())}
    return jwt.encode(payload, config.CFG["SECRET_KEY"], algorithm=ALGO)

def decode_token(token: str):
    try:
        data = jwt.decode(token, config.CFG["SECRET_KEY"], algorithms=[ALGO])
        return int(data.get("sub"))
    except Exception:
        return None

def coins_for_visits(visits: int) -> int:
    vpc = int(config.CFG["VISITS_PER_COIN"])
    return (visits + vpc - 1)//vpc

def count_active_threads():
    return sum(1 for t in TASK_THREADS.values() if t.is_alive())

VISIT_API = config.CFG["VISIT_API_TEMPLATE"]
HIT_INTERVAL = int(config.CFG["HIT_INTERVAL"])

# worker
def visit_worker(task_id:int):
    try:
        tasks = read("tasks", [])
        task = next((t for t in tasks if t["id"]==task_id), None)
        if not task: return
        uid = task["uid"]
        requested = int(task["requested_visits"])
        task["status"] = "running"; task["started_at"] = now_iso(); write("tasks", tasks)

        # snapshot start successful
        start_success = 0
        try:
            r = httpx.get(VISIT_API.format(uid=uid), timeout=15.0)
            if r.status_code==200:
                start_success = int(r.json().get("SuccessfulVisits", 0))
        except Exception:
            start_success = int(task.get("start_successful") or 0)

        task["start_successful"] = start_success
        task["last_successful"] = start_success
        write("tasks", tasks)

        TASK_PROGRESS[task_id] = {"start_successful": start_success, "last_successful": start_success, "gained": 0, "requested": requested, "status":"running"}
        STOP_FLAGS[task_id] = False

        while True:
            if STOP_FLAGS.get(task_id):
                tasks = read("tasks", [])
                t = next((x for x in tasks if x["id"]==task_id), None)
                if t:
                    t["status"]="stopped"
                    t.setdefault("note",""); t["note"] += f"\nStopped at {now_iso()}"
                    write("tasks", tasks)
                TASK_PROGRESS[task_id]["status"] = "stopped"
                break

            try:
                r = httpx.get(VISIT_API.format(uid=uid), timeout=15.0)
                if r.status_code == 200:
                    data = r.json()
                    cur = int(data.get("SuccessfulVisits", TASK_PROGRESS[task_id]["last_successful"]))
                    TASK_PROGRESS[task_id]["last_successful"] = cur
                    TASK_PROGRESS[task_id]["gained"] = cur - TASK_PROGRESS[task_id]["start_successful"]
                    tasks = read("tasks", [])
                    t = next((x for x in tasks if x["id"]==task_id), None)
                    if t:
                        t["last_successful"] = cur
                        write("tasks", tasks)
                    # completion
                    if TASK_PROGRESS[task_id]["gained"] >= requested:
                        tasks = read("tasks", [])
                        t = next((x for x in tasks if x["id"]==task_id), None)
                        if t:
                            t["status"]="completed"; t["completed_at"]=now_iso(); write("tasks", tasks)
                        TASK_PROGRESS[task_id]["status"]="completed"
                        break
                else:
                    tasks = read("tasks", [])
                    t = next((x for x in tasks if x["id"]==task_id), None)
                    if t:
                        t.setdefault("note",""); t["note"] += f"\nAPI error {r.status_code} at {now_iso()}"; write("tasks", tasks)
            except Exception as e:
                tasks = read("tasks", [])
                t = next((x for x in tasks if x["id"]==task_id), None)
                if t:
                    t.setdefault("note",""); t["note"] += f"\nException {str(e)} at {now_iso()}"; write("tasks", tasks)
            time.sleep(max(1, int(config.CFG["HIT_INTERVAL"])))
    finally:
        STOP_FLAGS.pop(task_id, None)
        TASK_THREADS.pop(task_id, None)

# ---------- Routes (API + pages) ----------

@app.route("/")
def index():
    return render_template("dashboard.html")

@app.route("/admin")
def admin_page():
    return render_template("admin.html")

# API: settings
@app.route("/api/settings", methods=["GET"])
def api_settings():
    s = read("settings", config.CFG)
    return {
        "VISITS_PER_COIN": int(s.get("VISITS_PER_COIN")),
        "RUPEE_PER_COIN": float(s.get("RUPEE_PER_COIN")),
        "SIGNUP_BONUS": int(s.get("SIGNUP_BONUS")),
        "HIT_INTERVAL": int(s.get("HIT_INTERVAL"))
    }

# register
@app.route("/api/register", methods=["POST"])
def api_register():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    ip = request.remote_addr
    if not username or not password:
        return jsonify({"error":"username/password required"}), 400
    users = read("users", [])
    if any(u.get("username","").lower()==username.lower() for u in users):
        return jsonify({"error":"username exists"}), 400
    if any(u.get("signup_ip")==ip for u in users):
        return jsonify({"error":"one account per ip/device allowed"}), 400
    uid = next_id(users)
    user = {"id": uid, "username": username, "password_hash": pwd.hash(password), "coins": int(config.CFG["SIGNUP_BONUS"]), "total_visits": 0, "is_admin": False, "banned": False, "signup_ip": ip, "created_at": now_iso(), "uid": None}
    users.append(user)
    audit = read("audit", [])
    audit.append({"id": next_id(audit), "actor":"system", "user_id": uid, "action":"signup", "amount": user["coins"], "note":"signup bonus", "created_at": now_iso()})
    write("audit", audit)
    write("users", users)
    return jsonify({"ok": True, "user_id": uid, "coins": user["coins"]})

# login
@app.route("/api/login", methods=["POST"])
def api_login():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    users = read("users", [])
    user = next((u for u in users if u.get("username","").lower()==username.lower()), None)
    if not user or not pwd.verify(password, user.get("password_hash","")):
        return jsonify({"error":"invalid credentials"}), 401
    if user.get("banned"):
        return jsonify({"error":"banned"}), 403
    token = create_token(user["id"])
    safe = {k:v for k,v in user.items() if k!="password_hash"}
    return jsonify({"access_token": token, "user": safe})

# start task
@app.route("/api/tasks/start", methods=["POST"])
def api_tasks_start():
    token = request.form.get("token")
    target_uid = request.form.get("uid")
    visits = int(request.form.get("visits") or 0)
    user_id = decode_token(token)
    if not user_id:
        return jsonify({"error":"auth required"}), 401
    users = read("users", [])
    user = next((u for u in users if u["id"]==user_id), None)
    if not user:
        return jsonify({"error":"user not found"}), 404
    tasks = read("tasks", [])
    running = sum(1 for t in tasks if t["user_id"]==user_id and t["status"] in ("pending","running"))
    if running >= int(config.CFG["MAX_CONCURRENT_TASKS_PER_USER"]):
        return jsonify({"error":"max concurrent tasks reached"}), 400
    coins_needed = coins_for_visits(visits)
    if user.get("coins",0) < coins_needed:
        return jsonify({"error":"insufficient coins"}), 400
    user["coins"] = user.get("coins",0) - coins_needed
    tid = next_id(tasks)
    now = now_iso()
    task = {"id": tid, "user_id": user_id, "uid": target_uid, "requested_visits": visits, "coins_deducted": coins_needed, "status":"pending", "start_successful": None, "last_successful": None, "created_at": now, "started_at": None, "completed_at": None, "note": ""}
    tasks.append(task)
    audit = read("audit", [])
    audit.append({"id": next_id(audit), "actor":"user", "user_id": user_id, "action":"start_task", "amount": -coins_needed, "note": f"requested {visits} uid {target_uid}", "created_at": now})
    write("audit", audit)
    write("users", users)
    write("tasks", tasks)

    with GLOBAL_LOCK:
        if count_active_threads() >= int(config.CFG["MAX_THREADS_TOTAL"]):
            return jsonify({"error":"server busy"}), 503
        th = threading.Thread(target=visit_worker, args=(tid,), daemon=True)
        TASK_THREADS[tid] = th
        th.start()
    return jsonify({"ok": True, "task_id": tid, "coins_used": coins_needed})

# stop
@app.route("/api/tasks/<int:task_id>/stop", methods=["POST"])
def api_tasks_stop(task_id):
    token = request.form.get("token")
    user_id = decode_token(token)
    if not user_id:
        return jsonify({"error":"auth required"}), 401
    tasks = read("tasks", [])
    t = next((x for x in tasks if x["id"]==task_id), None)
    if not t:
        return jsonify({"error":"task not found"}), 404
    if t["user_id"] != user_id:
        return jsonify({"error":"forbidden"}), 403
    STOP_FLAGS[task_id] = True
    return jsonify({"ok": True})

# tasks list
@app.route("/api/tasks", methods=["GET"])
def api_tasks_list():
    token = request.args.get("token")
    user_id = decode_token(token)
    if not user_id:
        return jsonify({"error":"auth required"}), 401
    tasks = read("tasks", [])
    user_tasks = [t for t in tasks if t["user_id"]==user_id]
    return jsonify({"tasks": user_tasks})

# single task
@app.route("/api/tasks/<int:task_id>", methods=["GET"])
def api_task_get(task_id):
    token = request.args.get("token")
    user_id = decode_token(token)
    if not user_id:
        return jsonify({"error":"auth required"}), 401
    tasks = read("tasks", [])
    t = next((x for x in tasks if x["id"]==task_id), None)
    if not t:
        return jsonify({"error":"not found"}), 404
    if t["user_id"] != user_id:
        return jsonify({"error":"forbidden"}), 403
    progress = TASK_PROGRESS.get(task_id)
    if progress:
        c = t.copy(); c.update(progress); return jsonify(c)
    return jsonify(t)

# history - for admin or user
@app.route("/api/history", methods=["GET"])
def api_history():
    admin_pass = request.args.get("admin_pass")
    if admin_pass and admin_pass == config.CFG["ADMIN_PASSWORD"]:
        return jsonify({"audit": read("audit", []), "tasks": read("tasks", []), "redeems": read("redeems", [])})
    token = request.args.get("token")
    user_id = decode_token(token)
    if not user_id:
        return jsonify({"error":"auth required"}), 401
    audit = [a for a in read("audit", []) if a.get("user_id")==user_id]
    tasks = [t for t in read("tasks", []) if t.get("user_id")==user_id]
    return jsonify({"audit": audit, "tasks": tasks})

# admin endpoints
@app.route("/api/admin/users", methods=["GET"])
def api_admin_users():
    admin_pass = request.args.get("admin_pass")
    if admin_pass != config.CFG["ADMIN_PASSWORD"]:
        return jsonify({"error":"admin auth failed"}), 401
    users = read("users", [])
    sanitized = [{k:v for k,v in u.items() if k!="password_hash"} for u in users]
    return jsonify({"users": sanitized})

@app.route("/api/admin/users/<int:uid>/add_coins", methods=["POST"])
def api_admin_add_coins(uid):
    admin_pass = request.form.get("admin_pass")
    coins = int(request.form.get("coins") or 0)
    if admin_pass != config.CFG["ADMIN_PASSWORD"]:
        return jsonify({"error":"admin auth failed"}), 401
    users = read("users", [])
    u = next((x for x in users if x["id"]==uid), None)
    if not u:
        return jsonify({"error":"not found"}), 404
    u["coins"] = u.get("coins",0) + coins
    audit = read("audit", [])
    audit.append({"id": next_id(audit), "actor":"admin", "user_id": uid, "action":"add_coins", "amount": coins, "note":"manual add", "created_at": now_iso()})
    write("audit", audit)
    write("users", users)
    return jsonify({"ok": True})

@app.route("/api/admin/redeems", methods=["GET"])
def api_admin_redeems():
    admin_pass = request.args.get("admin_pass")
    if admin_pass != config.CFG["ADMIN_PASSWORD"]:
        return jsonify({"error":"admin auth failed"}), 401
    redeems = read("redeems", [])
    return jsonify({"redeems": redeems})

@app.route("/api/admin/redeems/<int:rid>/approve", methods=["POST"])
def api_admin_redeem_approve(rid):
    admin_pass = request.form.get("admin_pass")
    if admin_pass != config.CFG["ADMIN_PASSWORD"]:
        return jsonify({"error":"admin auth failed"}), 401
    redeems = read("redeems", [])
    rec = next((r for r in redeems if r["id"]==rid), None)
    if not rec:
        return jsonify({"error":"not found"}), 404
    if rec["status"] != "pending":
        return jsonify({"ok": False, "msg": "already processed"})
    rpc = float(config.CFG["RUPEE_PER_COIN"])
    coins = int(rec["amount"] // rpc)
    users = read("users", [])
    u = next((x for x in users if x["id"]==rec["user_id"]), None)
    if u:
        u["coins"] = u.get("coins",0) + coins
    rec["status"] = "approved"
    audit = read("audit", [])
    audit.append({"id": next_id(audit), "actor":"admin", "user_id": rec["user_id"], "action":"redeem_approved", "amount": coins, "note": f"redeem {rid}", "created_at": now_iso()})
    write("audit", audit)
    write("users", users)
    write("redeems", redeems)
    return jsonify({"ok": True, "credited": coins})

# export files (admin)
@app.route("/export/<name>")
def export_file(name):
    admin_pass = request.args.get("admin_pass")
    if admin_pass != config.CFG["ADMIN_PASSWORD"]:
        return "admin auth required", 401
    mapping = {"users": config.CFG["FILES"]["users"], "tasks": config.CFG["FILES"]["tasks"], "redeems": config.CFG["FILES"]["redeems"], "audit": config.CFG["FILES"]["audit"], "settings": config.CFG["FILES"]["settings"]}
    path = mapping.get(name)
    if not path or not os.path.exists(path):
        return "not found", 404
    return send_file(path, as_attachment=True)

if __name__ == "__main__":
    for k,v in config.CFG["FILES"].items():
        read(k, [] if k!="settings" else config.CFG)
    print("✅ Visit System running locally at http://127.0.0.1:8000")
    app.run(host="0.0.0.0", port=8000)
