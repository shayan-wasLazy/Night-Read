import os, sqlite3, uuid, mimetypes
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(os.getenv("NIGHTREAD_DATA", "/data"))
BOOKS = BASE / "Books"
COVERS = BASE / "Covers"
DB = Path(os.getenv("NIGHTREAD_DB", "/appdata/nightread.db"))
for folder in (BOOKS, COVERS, DB.parent):
    folder.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="NightRead API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def now():
    return datetime.now(timezone.utc).isoformat()

def init_db():
    with conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS books(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, author TEXT NOT NULL,
            filename TEXT NOT NULL UNIQUE, format TEXT NOT NULL,
            progress INTEGER DEFAULT 0, created_at TEXT NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS bookmarks(
            id INTEGER PRIMARY KEY AUTOINCREMENT, book_id INTEGER NOT NULL,
            location TEXT NOT NULL, note TEXT DEFAULT '', created_at TEXT NOT NULL,
            FOREIGN KEY(book_id) REFERENCES books(id)
        )""")
        existing = {row["name"] for row in c.execute("PRAGMA table_info(books)").fetchall()}
        additions = {
            "original_title": "TEXT", "publication_year": "INTEGER",
            "genre": "TEXT", "series": "TEXT", "volume": "TEXT",
            "publisher": "TEXT", "description": "TEXT", "isbn": "TEXT",
            "cover_filename": "TEXT", "reading_status": "TEXT NOT NULL DEFAULT 'Want to Read'",
            "rating": "REAL", "notes": "TEXT", "updated_at": "TEXT"
        }
        for name, definition in additions.items():
            if name not in existing:
                c.execute(f"ALTER TABLE books ADD COLUMN {name} {definition}")
        c.execute("UPDATE books SET updated_at=COALESCE(updated_at, created_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_books_year ON books(publication_year)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_books_status ON books(reading_status)")
init_db()

def book_dict(row):
    item = dict(row)
    item["cover_url"] = f"/api/books/{item['id']}/cover" if item.get("cover_filename") else None
    item["decade"] = (item["publication_year"] // 10) * 10 if item.get("publication_year") else None
    return item

async def save_upload(upload: UploadFile, folder: Path, allowed: set[str], max_bytes: int):
    ext = Path(upload.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(415, f"Unsupported file type: {ext or 'unknown'}")
    name = uuid.uuid4().hex + ext
    dest = folder / name
    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, f"Upload exceeds {max_bytes // (1024*1024)} MB.")
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Uploaded file is empty.")
    return name

def clean_year(value: Optional[int]):
    if value is None:
        raise HTTPException(422, "Publication year is required.")
    current = datetime.now().year
    if value < 1 or value > current + 5:
        raise HTTPException(422, f"Publication year must be between 1 and {current + 5}.")
    return value

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "NightRead", "version": "2.0.0"}

@app.get("/api/books")
def list_books(q: str = "", decade: Optional[int] = None, status: Optional[str] = None,
               sort: str = "year", order: str = "asc", limit: int = Query(500, ge=1, le=2000),
               offset: int = Query(0, ge=0)):
    clauses, args = [], []
    if q.strip():
        clauses.append("(title LIKE ? OR author LIKE ? OR original_title LIKE ? OR series LIKE ?)")
        term = f"%{q.strip()}%"
        args.extend([term, term, term, term])
    if decade is not None:
        clauses.append("publication_year >= ? AND publication_year < ?")
        args.extend([decade, decade + 10])
    if status:
        clauses.append("reading_status = ?")
        args.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sort_col = {"year": "publication_year", "title": "title", "created": "created_at"}.get(sort, "publication_year")
    direction = "DESC" if order.lower() == "desc" else "ASC"
    with conn() as c:
        rows = c.execute(f"SELECT * FROM books{where} ORDER BY {sort_col} IS NULL, {sort_col} {direction}, id ASC LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
        total = c.execute(f"SELECT COUNT(*) FROM books{where}", args).fetchone()[0]
    return {"items": [book_dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}

@app.get("/api/books/decades")
def list_decades():
    with conn() as c:
        rows = c.execute("SELECT (publication_year / 10) * 10 AS decade, COUNT(*) AS count FROM books WHERE publication_year IS NOT NULL GROUP BY decade ORDER BY decade").fetchall()
    return [dict(r) for r in rows]

@app.post("/api/books")
async def add_book(title: str = Form(...), author: str = Form(...), publication_year: int = Form(...),
    cover: UploadFile = File(...), original_title: str = Form(""), genre: str = Form(""),
    series: str = Form(""), volume: str = Form(""), publisher: str = Form(""),
    description: str = Form(""), isbn: str = Form(""), reading_status: str = Form("Want to Read"),
    rating: Optional[float] = Form(None), notes: str = Form(""), book_file: Optional[UploadFile] = File(None)):
    title, author = title.strip(), author.strip()
    if not title or not author:
        raise HTTPException(422, "Title and author are required.")
    year = clean_year(publication_year)
    statuses = {"Want to Read", "Reading", "Completed", "On Hold"}
    if reading_status not in statuses:
        raise HTTPException(422, "Invalid reading status.")
    if rating is not None and not 0 <= rating <= 5:
        raise HTTPException(422, "Rating must be between 0 and 5.")
    cover_name = await save_upload(cover, COVERS, {".jpg", ".jpeg", ".png", ".webp"}, 10*1024*1024)
    book_name, fmt = f"metadata-{uuid.uuid4().hex}.none", "book"
    if book_file and book_file.filename:
        ext = Path(book_file.filename).suffix.lower()
        if ext not in {".epub", ".pdf", ".txt"}:
            (COVERS / cover_name).unlink(missing_ok=True)
            raise HTTPException(415, "Book file must be EPUB, PDF or TXT.")
        book_name = await save_upload(book_file, BOOKS, {".epub", ".pdf", ".txt"}, 100*1024*1024)
        fmt = ext[1:]
    stamp = now()
    with conn() as c:
        cur = c.execute("""INSERT INTO books(title,author,filename,format,progress,created_at,original_title,publication_year,genre,series,volume,publisher,description,isbn,cover_filename,reading_status,rating,notes,updated_at)
        VALUES(?,?,?,?,0,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (title,author,book_name,fmt,stamp,original_title.strip() or None,year,genre.strip() or None,series.strip() or None,volume.strip() or None,publisher.strip() or None,description.strip() or None,isbn.strip() or None,cover_name,reading_status,rating,notes.strip() or None,stamp))
        book_id = cur.lastrowid
        row = c.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    return book_dict(row)

@app.put("/api/books/{book_id}")
async def edit_book(book_id: int, title: str = Form(...), author: str = Form(...), publication_year: int = Form(...),
    cover: Optional[UploadFile] = File(None), original_title: str = Form(""), genre: str = Form(""),
    series: str = Form(""), volume: str = Form(""), publisher: str = Form(""),
    description: str = Form(""), isbn: str = Form(""), reading_status: str = Form("Want to Read"),
    rating: Optional[float] = Form(None), notes: str = Form("")):
    if not title.strip() or not author.strip():
        raise HTTPException(422, "Title and author are required.")
    year = clean_year(publication_year)
    if reading_status not in {"Want to Read", "Reading", "Completed", "On Hold"}:
        raise HTTPException(422, "Invalid reading status.")
    if rating is not None and not 0 <= rating <= 5:
        raise HTTPException(422, "Rating must be between 0 and 5.")
    with conn() as c:
        old = c.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    if not old:
        raise HTTPException(404, "Book not found.")
    new_cover = await save_upload(cover, COVERS, {".jpg", ".jpeg", ".png", ".webp"}, 10*1024*1024) if cover and cover.filename else old["cover_filename"]
    stamp = now()
    with conn() as c:
        c.execute("""UPDATE books SET title=?,author=?,original_title=?,publication_year=?,genre=?,series=?,volume=?,publisher=?,description=?,isbn=?,cover_filename=?,reading_status=?,rating=?,notes=?,updated_at=? WHERE id=?""",
        (title.strip(),author.strip(),original_title.strip() or None,year,genre.strip() or None,series.strip() or None,volume.strip() or None,publisher.strip() or None,description.strip() or None,isbn.strip() or None,new_cover,reading_status,rating,notes.strip() or None,stamp,book_id))
        row = c.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    if new_cover != old["cover_filename"] and old["cover_filename"]:
        (COVERS / old["cover_filename"]).unlink(missing_ok=True)
    return book_dict(row)

@app.get("/api/books/{book_id}/cover")
def get_cover(book_id: int):
    with conn() as c:
        row = c.execute("SELECT cover_filename FROM books WHERE id=?", (book_id,)).fetchone()
    if not row or not row["cover_filename"]:
        raise HTTPException(404, "Cover not found.")
    path = COVERS / row["cover_filename"]
    if not path.is_file():
        raise HTTPException(404, "Cover file missing.")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=3600"})

@app.patch("/api/books/{book_id}/status")
def update_status(book_id: int, payload: dict):
    status = payload.get("reading_status")
    if status not in {"Want to Read", "Reading", "Completed", "On Hold"}:
        raise HTTPException(422, "Invalid reading status.")
    with conn() as c:
        cur = c.execute("UPDATE books SET reading_status=?,updated_at=? WHERE id=?", (status,now(),book_id))
        if cur.rowcount == 0: raise HTTPException(404, "Book not found.")
    return {"id": book_id, "reading_status": status}

@app.patch("/api/books/{book_id}/progress")
def update_progress(book_id: int, payload: dict):
    progress = max(0, min(100, int(payload.get("progress", 0))))
    with conn() as c:
        cur = c.execute("UPDATE books SET progress=?,updated_at=? WHERE id=?", (progress,now(),book_id))
        if cur.rowcount == 0: raise HTTPException(404, "Book not found.")
    return {"id": book_id, "progress": progress}

@app.get("/api/books/{book_id}/content")
def book_content(book_id: int):
    with conn() as c:
        row = c.execute("SELECT filename,format FROM books WHERE id=?", (book_id,)).fetchone()
    if not row: raise HTTPException(404, "Book not found.")
    path = BOOKS / row["filename"]
    if row["format"] == "book": raise HTTPException(404, "No reading file was attached to this book.")
    if not path.is_file(): raise HTTPException(404, "Book file missing.")
    if row["format"] != "txt":
        return FileResponse(path, media_type="application/pdf" if row["format"] == "pdf" else "application/epub+zip")
    return PlainTextResponse(path.read_text(encoding="utf-8", errors="replace"))

@app.get("/api/books/{book_id}/download")
def download(book_id: int):
    with conn() as c:
        row = c.execute("SELECT filename,format FROM books WHERE id=?", (book_id,)).fetchone()
    if not row: raise HTTPException(404, "Book not found.")
    if row["format"] == "book": raise HTTPException(404, "No reading file attached.")
    path = BOOKS / row["filename"]
    if not path.is_file(): raise HTTPException(404, "Book file missing.")
    return FileResponse(path, filename=path.name)

@app.delete("/api/books/{book_id}")
def delete_book(book_id: int):
    with conn() as c:
        row = c.execute("SELECT filename,cover_filename FROM books WHERE id=?", (book_id,)).fetchone()
        if not row: raise HTTPException(404, "Book not found.")
        c.execute("DELETE FROM bookmarks WHERE book_id=?", (book_id,))
        c.execute("DELETE FROM books WHERE id=?", (book_id,))
    if row["filename"] and not row["filename"].startswith("metadata-"):
        (BOOKS / row["filename"]).unlink(missing_ok=True)
    if row["cover_filename"]:
        (COVERS / row["cover_filename"]).unlink(missing_ok=True)
    return {"deleted": book_id}

FRONTEND = Path("/frontend")
if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
