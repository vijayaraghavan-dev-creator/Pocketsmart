import os, uuid, json, sqlite3, hmac, hashlib, secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from contextlib import asynccontextmanager
import gemini_utils as g

load_dotenv()
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "pocketsmart.db")
SECRET = os.getenv("SECRET_KEY", "dev-secret-change-me")
UPLOADS = os.path.join(BASE, "static", "uploads")

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

@asynccontextmanager
async def lifespan(app):  # startup: create tables, check config
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, email TEXT, pw TEXT, created TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, user_id INTEGER, category TEXT, budget REAL, inputs TEXT, result TEXT, created TEXT)")
    if not os.getenv("GEMINI_API_KEY") or "paste_your_key" in os.getenv("GEMINI_API_KEY", ""):
        print("WARNING: GEMINI_API_KEY missing in .env - fallback suggestions will be used.")
    yield

app = FastAPI(title="PocketSmart AI", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))

# ---------- auth helpers ----------
def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()

def check_pw(pw, stored):
    return hmac.compare_digest(hash_pw(pw, stored.split("$")[0]), stored)

def make_token(username):
    return jwt.encode({"sub": username, "exp": datetime.now(timezone.utc) + timedelta(hours=8)}, SECRET, "HS256")

def user_from_request(request: Request):
    token = request.cookies.get("access_token")
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
    if not token:
        return None
    try:
        name = jwt.decode(token, SECRET, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        return None
    with db() as c:
        row = c.execute("SELECT * FROM users WHERE username=?", (name,)).fetchone()
    return dict(row) if row else None

def get_current_user(request: Request):
    u = user_from_request(request)
    if not u:
        raise HTTPException(401, "Not authenticated")
    return u

@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException):
    from fastapi.responses import JSONResponse
    if exc.status_code == 401 and "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/login", 303)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

def page(request, name, user=None, **ctx):
    return templates.TemplateResponse(request, name, {"user": user, **ctx})

def login_response(username):
    r = RedirectResponse("/dashboard", 303)
    r.set_cookie("access_token", make_token(username), httponly=True, samesite="lax", max_age=8 * 3600)
    return r

# ---------- public pages & auth ----------
@app.get("/")
def index(request: Request):
    return page(request, "index.html", user_from_request(request))

@app.get("/register")
def register_page(request: Request):
    return page(request, "register.html", user_from_request(request))

@app.post("/register")
def register(request: Request, username: str = Form(...), email: str = Form(...), password: str = Form(...)):
    username = username.strip()
    if len(username) < 3 or len(password) < 6:
        return page(request, "register.html", error="Username needs 3+ chars and password 6+ chars.")
    try:
        with db() as c:
            c.execute("INSERT INTO users(username,email,pw,created) VALUES(?,?,?,?)",
                      (username, email.strip(), hash_pw(password), datetime.now().isoformat(timespec="seconds")))
    except sqlite3.IntegrityError:
        return page(request, "register.html", error="That username is already taken.")
    return login_response(username)

@app.get("/login")
def login_page(request: Request):
    return page(request, "login.html", user_from_request(request))

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    with db() as c:
        row = c.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
    if not row or not check_pw(password, row["pw"]):
        return page(request, "login.html", error="Invalid username or password.")
    return login_response(row["username"])

@app.get("/logout")
def logout():
    r = RedirectResponse("/login", 303)
    r.delete_cookie("access_token")
    return r

@app.post("/token")
def token(form: OAuth2PasswordRequestForm = Depends()):
    with db() as c:
        row = c.execute("SELECT * FROM users WHERE username=?", (form.username,)).fetchone()
    if not row or not check_pw(form.password, row["pw"]):
        raise HTTPException(401, "Incorrect username or password")
    return {"access_token": make_token(row["username"]), "token_type": "bearer"}

@app.get("/session-info")
def session_info(user=Depends(get_current_user)):
    return {"user_id": user["id"], "username": user["username"], "logged_in": True}

@app.get("/session-data")
def session_data(user=Depends(get_current_user)):
    with db() as c:
        rows = c.execute("SELECT category, COUNT(*) n, SUM(budget) b FROM history WHERE user_id=? GROUP BY category", (user["id"],)).fetchall()
    return {"username": user["username"], "member_since": user["created"], "usage": {r["category"]: {"queries": r["n"], "total_budget": r["b"]} for r in rows}}

# ---------- planner pages ----------
@app.get("/dashboard")
def dashboard(request: Request, user=Depends(get_current_user)):
    with db() as c:
        recent = c.execute("SELECT * FROM history WHERE user_id=? ORDER BY id DESC LIMIT 5", (user["id"],)).fetchall()
        total = c.execute("SELECT COUNT(*) FROM history WHERE user_id=?", (user["id"],)).fetchone()[0]
    return page(request, "dashboard.html", user, recent=recent, total=total)

for _slug, _tpl in [("home-planner", "home_planner.html"), ("party-planner", "party_planner.html"), ("jewelry-planner", "jewelry_planner.html")]:
    def _make(tpl):
        def view(request: Request, user=Depends(get_current_user)):
            return page(request, tpl, user)
        return view
    app.get("/" + _slug)(_make(_tpl))

# ---------- generation ----------
def run(user, category, budget, inputs, details, image=None):
    if budget <= 0 or budget > 100_000_000:
        raise HTTPException(400, "Please enter a valid budget greater than 0.")
    result = g.recommend(category, budget, details, image)
    with db() as c:
        cur = c.execute("INSERT INTO history(user_id,category,budget,inputs,result,created) VALUES(?,?,?,?,?,?)",
                        (user["id"], category, budget, json.dumps(inputs), json.dumps(result), datetime.now().isoformat(timespec="seconds")))
    result["id"] = cur.lastrowid
    return result

@app.post("/generate-home")
def generate_home(budget: float = Form(...), rooms: str = Form(...), items: str = Form(...), style: str = Form("modern"),
                  user=Depends(get_current_user)):
    d = {"rooms": rooms, "items": items, "style": style}
    return run(user, "home", budget, d, f"Rooms: {rooms}\nItems and quantities needed: {items}\nStyle: {style}")

@app.post("/generate-party")
def generate_party(budget: float = Form(...), guests: int = Form(...), event_type: str = Form(...), venue: str = Form(""),
                   user=Depends(get_current_user)):
    if guests < 1:
        raise HTTPException(400, "Guest count must be at least 1.")
    d = {"guests": guests, "event_type": event_type, "venue": venue}
    kind = {"wedding": "Weddings need larger venue and decor share.", "corporate": "Corporate events favour catering and venue."}.get(event_type.lower(), "")
    return run(user, "party", budget, d, f"Event: {event_type}\nGuests: {guests}\nVenue details: {venue}\n"
               f"Allocate the budget proportionally across catering, decoration, entertainment and venue/stay. {kind}")

@app.post("/generate-jewelry")
async def generate_jewelry(budget: float = Form(...), occasion: str = Form(...), style: str = Form("elegant"),
                           image: Optional[UploadFile] = File(None), user=Depends(get_current_user)):
    img = None
    d = {"occasion": occasion, "style": style}
    if image and image.filename:
        if image.content_type not in ("image/jpeg", "image/png", "image/webp"):
            raise HTTPException(400, "Upload a JPG, PNG or WEBP image.")
        data = await image.read()
        if len(data) > 5 * 1024 * 1024:
            raise HTTPException(400, "Image must be under 5 MB.")
        ext = image.content_type.split("/")[1]
        name = f"{uuid.uuid4().hex}.{ext}"
        with open(os.path.join(UPLOADS, name), "wb") as f:
            f.write(data)
        d["image"] = name
        img = (data, image.content_type)
    note = "An outfit image is attached: match its colours and aesthetics." if img else ""
    return run(user, "jewelry", budget, d, f"Occasion: {occasion}\nStyle preference: {style}\n{note}", img)

# ---------- history ----------
@app.get("/history")
def history(request: Request, user=Depends(get_current_user)):
    with db() as c:
        rows = c.execute("SELECT id,category,budget,created FROM history WHERE user_id=? ORDER BY id DESC", (user["id"],)).fetchall()
    return page(request, "history.html", user, rows=rows)

@app.get("/recommendations-details")
def details(id: int, user=Depends(get_current_user)):
    with db() as c:
        row = c.execute("SELECT * FROM history WHERE id=? AND user_id=?", (id, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "Recommendation not found")
    return {**json.loads(row["result"]), "id": row["id"], "category": row["category"], "inputs": json.loads(row["inputs"]), "created": row["created"]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
