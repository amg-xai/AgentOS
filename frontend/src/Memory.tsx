import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { api, date, errorMessage } from './api';
import type { Note } from './api';
import { ErrorNotice } from './components';
export function Memory({ canWrite, demo = false }: { canWrite: boolean; demo?: boolean }) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [query, setQuery] = useState('');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api<Note[]>(
      `/memory?limit=100&query=${encodeURIComponent(query)}`,
      undefined,
      controller.signal,
    )
      .then((n) => {
        if (controller.signal.aborted) return;
        setNotes(n);
        setError('');
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(errorMessage(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [query, revision]);
  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await api('/memory', { title: title.trim(), content: content.trim() });
      setTitle('');
      setContent('');
      setRevision((r) => r + 1);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="info">
        {demo
          ? 'Demo notes stay in separate local demo history. Scripted responses do not use their content. '
          : 'Relevant notes may be sent to your configured model during investigation. '}
        Retrieval uses keyword overlap, not semantic search.
      </div>
      <ErrorNotice message={error} />
      <div className="memory-layout">
        <section className="panel">
          <div className="section-heading">
            <h2>Project context</h2>
            <span className="scope-tag">Lexical retrieval</span>
          </div>
          <label htmlFor="search">Search notes</label>
          <input
            id="search"
            type="search"
            placeholder="Search project context…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            maxLength={8000}
          />
          {loading ? (
            <p role="status">Loading notes…</p>
          ) : !notes.length ? (
            <div className="empty">
              <h3>{query ? 'No matching notes' : 'A fresh workspace'}</h3>
              <p>Add decisions, constraints, or context your agents should remember.</p>
            </div>
          ) : (
            notes.map((n) => (
              <article className="note" key={n.id}>
                <h3>{n.title}</h3>
                <p>{n.content}</p>
                {n.artifact_refs.length > 0 && (
                  <small>{n.artifact_refs.length} linked artifact(s)</small>
                )}
                <small>{date(n.created_at)}</small>
              </article>
            ))
          )}
        </section>
        <section className="panel">
          <h2>Add a note</h2>
          <form onSubmit={save}>
            <label htmlFor="note-title">Title</label>
            <input
              id="note-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              maxLength={160}
              disabled={!canWrite}
            />
            <label htmlFor="note-content">Context</label>
            <textarea
              id="note-content"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              required
              maxLength={8000}
              rows={7}
              placeholder="Keep calculations exact. Preserve existing test coverage."
              disabled={!canWrite}
            />
            <button
              className="primary"
              disabled={!canWrite || busy || !title.trim() || !content.trim()}
            >
              {busy ? 'Saving…' : 'Save note'}
            </button>
          </form>
        </section>
      </div>
    </>
  );
}
