import os, sqlite3, uuid
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
BASE=Path(os.getenv("NIGHTREAD_DATA","/data")); BOOKS=BASE/"Books"; DB=Path(os.getenv("NIGHTREAD_DB","/appdata/nightread.db"))
BOOKS.mkdir(parents=True,exist_ok=True); DB.parent.mkdir(parents=True,exist_ok=True)
app=FastAPI(title="NightRead API",version="1.0.0")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
def conn():
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;return c
with conn() as c:
 c.execute("""CREATE TABLE IF NOT EXISTS books(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,author TEXT NOT NULL,filename TEXT NOT NULL UNIQUE,format TEXT NOT NULL,progress INTEGER DEFAULT 0,created_at TEXT NOT NULL)""")
 c.execute("""CREATE TABLE IF NOT EXISTS bookmarks(id INTEGER PRIMARY KEY AUTOINCREMENT,book_id INTEGER NOT NULL,location TEXT NOT NULL,note TEXT DEFAULT '',created_at TEXT NOT NULL,FOREIGN KEY(book_id) REFERENCES books(id))""")
@app.get("/api/health")
def health(): return {"status":"ok","service":"NightRead"}
@app.get("/api/books")
def list_books():
 with conn() as c: rows=c.execute("SELECT * FROM books ORDER BY created_at DESC").fetchall()
 return [dict(r) for r in rows]
@app.post("/api/books")
async def add_book(file:UploadFile=File(...)):
 ext=Path(file.filename or "").suffix.lower()
 if ext not in {".epub",".pdf",".txt"}: raise HTTPException(415,"Only EPUB, PDF and TXT files are supported.")
 safe=Path(file.filename or "book"+ext).name; name=f"{uuid.uuid4().hex}{ext}"; dest=BOOKS/name; size=0
 with dest.open("wb") as out:
  while chunk:=await file.read(1024*1024):
   size+=len(chunk)
   if size>100*1024*1024: dest.unlink(missing_ok=True);raise HTTPException(413,"Maximum upload size is 100 MB.")
   out.write(chunk)
 title=Path(safe).stem.replace("_"," ").replace("-"," ").strip() or "Untitled"
 with conn() as c:
  cur=c.execute("INSERT INTO books(title,author,filename,format,progress,created_at) VALUES(?,?,?,?,0,?)",(title,"Unknown author",name,ext[1:],datetime.now(timezone.utc).isoformat()))
 return {"id":cur.lastrowid,"title":title,"filename":name,"format":ext[1:]}
@app.get("/api/books/{book_id}/content")
def book_content(book_id:int):
 with conn() as c: row=c.execute("SELECT filename,format FROM books WHERE id=?",(book_id,)).fetchone()
 if not row: raise HTTPException(404,"Book not found")
 path=BOOKS/row["filename"]
 if not path.is_file(): raise HTTPException(404,"Book file missing")
 if row["format"]!="txt": return FileResponse(path,media_type="application/pdf" if row["format"]=="pdf" else "application/epub+zip")
 return PlainTextResponse(path.read_text(encoding="utf-8",errors="replace"))
@app.patch("/api/books/{book_id}/progress")
def update_progress(book_id:int,payload:dict):
 progress=max(0,min(100,int(payload.get("progress",0))))
 with conn() as c:
  cur=c.execute("UPDATE books SET progress=? WHERE id=?",(progress,book_id))
  if cur.rowcount==0: raise HTTPException(404,"Book not found")
 return {"id":book_id,"progress":progress}
@app.get("/api/books/{book_id}/download")
def download(book_id:int):
 with conn() as c: row=c.execute("SELECT filename FROM books WHERE id=?",(book_id,)).fetchone()
 if not row: raise HTTPException(404,"Book not found")
 path=BOOKS/row["filename"]
 if not path.is_file(): raise HTTPException(404,"Book file missing")
 return FileResponse(path,filename=path.name)
@app.delete("/api/books/{book_id}")
def delete_book(book_id:int):
 with conn() as c:
  row=c.execute("SELECT filename FROM books WHERE id=?",(book_id,)).fetchone()
  if not row: raise HTTPException(404,"Book not found")
  (BOOKS/row["filename"]).unlink(missing_ok=True);c.execute("DELETE FROM bookmarks WHERE book_id=?",(book_id,));c.execute("DELETE FROM books WHERE id=?",(book_id,))
 return {"deleted":book_id}
FRONTEND=Path("/frontend")
if FRONTEND.exists(): app.mount("/",StaticFiles(directory=FRONTEND,html=True),name="frontend")