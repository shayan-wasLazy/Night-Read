import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { ArrowLeft, ArrowRight, BookOpen, Bookmark, ChevronLeft, ChevronRight, Library, Moon, Search, Sun, Upload, X } from 'lucide-react';

type Book = { id: number; title: string; author: string; format: string; filename: string; progress: number; created_at: string };
const API = '/api';
const palette = ['#5a2928', '#343b50', '#765039', '#43364a', '#6b3435', '#394052', '#66513d', '#493b38'];

function bookColor(index: number) { return palette[index % palette.length]; }
function splitIntoPages(value: string, chars = 1450) {
  const words = value.split(/\s+/);
  const pages: string[] = [];
  let page = '';
  for (const word of words) {
    if ((page + ' ' + word).length > chars && page) { pages.push(page); page = word; }
    else page += (page ? ' ' : '') + word;
  }
  if (page) pages.push(page);
  return pages.length ? pages : [''];
}

export default function App() {
  const [books, setBooks] = useState<Book[]>([]);
  const [selected, setSelected] = useState(0);
  const [query, setQuery] = useState('');
  const [reader, setReader] = useState<Book | null>(null);
  const [uploading, setUploading] = useState(false);
  const [toast, setToast] = useState('');
  const input = useRef<HTMLInputElement>(null);

  const load = async () => {
    try {
      const response = await fetch(API + '/books');
      if (response.ok) {
        const data: Book[] = await response.json();
        setBooks(data);
        setSelected(current => Math.min(current, Math.max(0, data.length - 1)));
      }
    } catch { /* server may be offline */ }
  };
  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => books.filter(book => (book.title + ' ' + book.author).toLowerCase().includes(query.toLowerCase())), [books, query]);
  const active = filtered[selected] || filtered[0];
  const notify = (message: string) => { setToast(message); window.setTimeout(() => setToast(''), 2800); };

  const upload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    setUploading(true);
    let added = 0;
    for (const file of files) {
      const form = new FormData();
      form.append('file', file);
      try { const response = await fetch(API + '/books', { method: 'POST', body: form }); if (response.ok) added++; } catch { /* handled below */ }
    }
    await load();
    setUploading(false);
    notify(added ? `Added ${added} book${added === 1 ? '' : 's'} to your shelf.` : 'Upload failed. Check your connection to NightRead.');
    event.target.value = '';
  };

  const move = (direction: number) => setSelected(current => Math.max(0, Math.min(filtered.length - 1, current + direction)));

  return <main className="library-screen">
    <header className="library-top">
      <button className="home-title" onClick={() => { setReader(null); setQuery(''); }}>Library</button>
      <div className="top-tools">
        <label className="shelf-search"><Search size={15}/><input value={query} onChange={event => { setQuery(event.target.value); setSelected(0); }} placeholder="Find a book"/></label>
        <button className="upload-button" onClick={() => input.current?.click()}><Upload size={15}/><span>{uploading ? 'ADDING' : 'ADD BOOK'}</span></button>
        <input ref={input} type="file" accept=".epub,.pdf,.txt" multiple hidden onChange={upload}/>
      </div>
    </header>

    <section className="shelf-intro"><h1>Your library</h1></section>

    {filtered.length ? <>
      <section className="spine-stage" aria-label="Book shelf carousel">
        <button className="shelf-arrow" onClick={() => move(-1)} disabled={selected <= 0} aria-label="Previous book"><ArrowLeft size={18}/></button>
        <div className="spine-track">
          {filtered.map((book, index) => {
            const distance = index - selected;
            return <button key={book.id} className={'spine-card ' + (index === selected ? 'spine-active' : '')} style={{ '--book-color': bookColor(index), '--distance': distance } as CSSProperties} onClick={() => setSelected(index)} title={book.title}>
              {index === selected ? <span className="cover-face"><span className="cover-kicker">NIGHTREAD LIBRARY</span><span className="cover-art-mark">✳</span><strong>{book.title}</strong><small>{book.author}</small><i>{String(index + 1).padStart(2, '0')}</i></span> : <><span className="spine-title">{book.title}</span><span className="spine-author">{book.author}</span><span className="spine-mark">{String(index + 1).padStart(2, '0')}</span></>}
            </button>;
          })}
        </div>
        <button className="shelf-arrow" onClick={() => move(1)} disabled={selected >= filtered.length - 1} aria-label="Next book"><ArrowRight size={18}/></button>
      </section>
      <section className="selected-book">
        <h2>{active?.title}</h2><p>{active?.author}</p>
        <div className="selected-actions"><button className="open-book" onClick={() => active && setReader(active)}><BookOpen size={15}/> {active?.progress ? 'CONTINUE READING' : 'OPEN BOOK'} <ArrowRight size={15}/></button><span>{active?.progress || 0}% READ</span></div>
      </section>
    </> : <section className="empty-shelf">
      <div className="empty-shelf-line"/>
      <div className="empty-archive-visual"><span className="empty-spine one"/><span className="empty-spine two"/><span className="empty-feature"><b>BOOK</b></span><span className="empty-spine three"/><span className="empty-spine four"/></div>
      <h2>{books.length ? 'No books found' : 'No books yet'}</h2>
      {!books.length && <button className="open-book" onClick={() => input.current?.click()}><Upload size={15}/> ADD BOOK</button>}
    </section>}

    
    {reader && <Reader book={reader} onClose={() => { setReader(null); load(); }} onProgress={progress => setBooks(old => old.map(book => book.id === reader.id ? { ...book, progress } : book))}/>}
    {toast && <div className="toast">{toast}</div>}
  </main>;
}

function Reader({ book, onClose, onProgress }: { book: Book; onClose: () => void; onProgress: (progress: number) => void }) {
  const [content, setContent] = useState('Loading your book…');
  const [page, setPage] = useState(0);
  const [night, setNight] = useState(false);
  const [fontSize, setFontSize] = useState(17);
  const pages = useMemo(() => splitIntoPages(content), [content]);
  const isText = book.format.toLowerCase() === 'txt' || book.filename.toLowerCase().endsWith('.txt');

  useEffect(() => {
    if (!isText) { setContent('This file is stored on your NightRead server. The dedicated EPUB/PDF page renderer is being added; use the original file link below in the meantime.'); return; }
    fetch(API + '/books/' + book.id + '/content').then(response => response.text()).then(setContent).catch(() => setContent('Unable to load this book. Please check your connection.'));
  }, [book.id, isText]);

  const saveProgress = () => {
    const progress = Math.min(100, Math.round(((page + 1) / Math.max(pages.length, 1)) * 100));
    fetch(API + '/' + 'books/' + book.id + '/progress', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ progress }) });
    onProgress(progress);
  };

  return <div className={'reader-view ' + (night ? 'reader-night' : '')}>
    <aside className="reader-sidebar">
      <div className="reader-brand">N<span>.</span></div>
      <div className="reader-user"><div className="reader-avatar">S</div><small>NOW READING</small><b>{book.title}</b></div>
      <div className="reader-side-links"><span><Library size={15}/> My shelf</span><span><Bookmark size={15}/> Bookmarks</span></div>
      <div className="reader-side-bottom"><span>PRIVATE READING ROOM</span><span>SYNCED TO HOME SERVER</span></div>
    </aside>
    <section className="reading-area">
      <header className="reading-header"><button className="back-to-shelf" onClick={onClose}><ChevronLeft size={17}/> BACK TO SHELF</button><div className="reading-breadcrumb">{book.title} <span>\</span> {isText ? 'Reading' : book.format.toUpperCase()}</div><div className="reading-controls"><button onClick={() => setFontSize(size => Math.max(14, size - 1))}>A−</button><button onClick={() => setFontSize(size => Math.min(24, size + 1))}>A+</button><button onClick={() => setNight(value => !value)} aria-label="Toggle reading theme">{night ? <Sun size={16}/> : <Moon size={16}/>}</button></div></header>
      <div className="paper-wrap"><article className="reading-paper" style={{ fontSize: fontSize + 'px' }}>
        <div className="paper-page-number">{page + 1}</div>
        <div className="paper-columns">{isText ? <p>{pages[page]}</p> : <div className="format-notice"><BookOpen size={23}/><h2>Your book is safe on the shelf.</h2><p>{content}</p><a href={API + '/books/' + book.id + '/download'} target="_blank" rel="noreferrer">OPEN ORIGINAL FILE <ArrowRight size={14}/></a></div>}</div>
      </article></div>
      <div className="page-strip"><button onClick={() => setPage(value => Math.max(0, value - 1))} disabled={page === 0}><ChevronLeft size={17}/></button><div className="page-thumbnails">{(isText ? pages : ['Original file']).map((_, index) => <button key={index} className={page === index ? 'page-thumb active-thumb' : 'page-thumb'} onClick={() => setPage(index)}><span>{index + 1}</span></button>)}</div><button onClick={() => setPage(value => Math.min(pages.length - 1, value + 1))} disabled={!isText || page >= pages.length - 1}><ChevronRight size={17}/></button></div>
      <div className="reader-bottom"><span>{book.title}</span><span>PAGE {page + 1} OF {isText ? pages.length : '—'}</span><button onClick={saveProgress}>SAVE READING POSITION <ArrowRight size={13}/></button></div>
    </section>
    <button className="close-reader" onClick={onClose} aria-label="Close reader"><X size={18}/></button>
  </div>;
}
