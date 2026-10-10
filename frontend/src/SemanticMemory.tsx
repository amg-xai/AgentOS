import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api, errorMessage } from './api';
import type { Note } from './api';
import { ErrorNotice } from './components';
import { MemoryArtifact } from './MemoryArtifact';

interface IndexStatus {
  configured: boolean;
  generation: number;
  indexed_chunks: number;
  omitted_sources: number;
  configuration_error?: string | null;
}
interface Hit {
  kind: 'note' | 'mission' | 'artifact';
  id: string;
  title: string;
  profile: string | null;
  mission_id: string | null;
  digest: string;
  evidence: string;
  start: number;
  end: number;
  excerpt: string;
  similarity: number;
}
interface Results {
  generation: number;
  hits: Hit[];
  indexed_chunks: number;
  omitted_sources: number;
  stale_sources: number;
  invalid_sources: number;
}

export function SemanticMemory({
  canWrite,
  onOpenMission,
}: {
  canWrite: boolean;
  onOpenMission?: (id: string) => void;
}) {
  const [status, setStatus] = useState<IndexStatus | null>(null);
  const [query, setQuery] = useState('');
  const [profile, setProfile] = useState('');
  const [mission, setMission] = useState('');
  const [kind, setKind] = useState('');
  const [result, setResult] = useState<Results | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<Note | null>(null);
  const [artifact, setArtifact] = useState<Hit | null>(null);
  const active = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    active.current = controller;
    api<IndexStatus>('/memory/semantic/status', undefined, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setStatus(value);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(errorMessage(e));
      });
    return () => active.current?.abort();
  }, []);
  function clear() {
    active.current?.abort();
    setResult(null);
    setNote(null);
    setArtifact(null);
    setBusy(false);
    setError('');
  }
  async function request(path: string, body?: object) {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError('');
    setResult(null);
    setNote(null);
    setArtifact(null);
    try {
      if (path.endsWith('/index')) {
        const value = await api<IndexStatus>(path, body, controller.signal);
        if (!controller.signal.aborted) setStatus(value);
      } else {
        const value = await api<Results>(path, body, controller.signal);
        if (!controller.signal.aborted) setResult(value);
      }
    } catch (e) {
      if (!controller.signal.aborted) setError(errorMessage(e));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  function search(event: FormEvent) {
    event.preventDefault();
    void request('/memory/semantic/search', {
      query: query.trim(),
      profile: profile || null,
      mission_id: mission.trim() || null,
      kind: kind || null,
    });
  }
  async function openNote(hit: Hit) {
    clear();
    const controller = new AbortController();
    active.current = controller;
    try {
      const value = await api<Note>(
        `/memory/notes/${encodeURIComponent(hit.id)}`,
        undefined,
        controller.signal,
      );
      if (!controller.signal.aborted) setNote(value);
    } catch (e) {
      if (!controller.signal.aborted) setError(errorMessage(e));
    }
  }
  return (
    <section className="panel" aria-label="Semantic memory search">
      <h2>Semantic memory search</h2>
      <p>
        Search local notes, stored mission outcomes and approved text artifacts. Similarity is not
        confidence or factual verification. Retrieved evidence does not change agent inputs or
        approvals.
      </p>
      <p>
        Coverage: newest 1,000 local notes and 200 missions. Omission counts apply within this
        window; older history remains available in Mission Control.
      </p>
      <ErrorNotice message={error || status?.configuration_error || ''} />
      {!status ? (
        error ? (
          <p>Semantic index status unavailable. Close this panel and reopen it to retry.</p>
        ) : (
          <p role="status">Loading semantic index status…</p>
        )
      ) : (
        <>
          <p>
            Index generation {status.generation} · {status.indexed_chunks} chunks ·{' '}
            {status.omitted_sources} omitted sources
          </p>
          {!status.configured && (
            <p>
              Local embeddings are disabled or unavailable. No model is downloaded or called
              automatically. Keyword search remains available separately.
            </p>
          )}
          <button
            disabled={!canWrite || !status.configured || busy}
            onClick={() => void request('/memory/semantic/index', {})}
          >
            Rebuild semantic index
          </button>
          {!canWrite && (
            <p>Viewer access: search and inspect; rebuilding requires Operator or Admin.</p>
          )}
          <form onSubmit={search}>
            <label htmlFor="semantic-query">Meaning to find</label>
            <input
              id="semantic-query"
              type="search"
              value={query}
              required
              maxLength={2000}
              onChange={(e) => {
                clear();
                setQuery(e.target.value);
              }}
            />
            <div className="history-filters">
              <label>
                Memory profile
                <select
                  value={profile}
                  onChange={(e) => {
                    clear();
                    setProfile(e.target.value);
                  }}
                >
                  <option value="">All profiles and shared notes</option>
                  <option value="developer">Developer</option>
                  <option value="creator">Creator</option>
                  <option value="student">Student</option>
                </select>
              </label>
              <label>
                Memory source
                <select
                  value={kind}
                  onChange={(e) => {
                    clear();
                    setKind(e.target.value);
                  }}
                >
                  <option value="">All sources</option>
                  <option value="note">Notes</option>
                  <option value="mission">Mission outcomes</option>
                  <option value="artifact">Approved artifacts</option>
                </select>
              </label>
              <label>
                Memory mission ID
                <input
                  value={mission}
                  maxLength={160}
                  onChange={(e) => {
                    clear();
                    setMission(e.target.value);
                  }}
                />
              </label>
            </div>
            <button
              className="primary"
              disabled={busy || !query.trim() || (!status.configured && status.indexed_chunks > 0)}
            >
              Search semantic memory
            </button>
          </form>
        </>
      )}
      {busy && <p role="status">Processing semantic memory request…</p>}
      {result && (
        <>
          <p>
            Result generation {result.generation} · {result.hits.length} matches ·{' '}
            {result.stale_sources} stale sources · {result.invalid_sources} invalid sources ·{' '}
            {result.omitted_sources} omitted sources
          </p>
          {!result.indexed_chunks ? (
            <p>
              The semantic index is empty. Rebuild it after local embeddings are explicitly
              configured.
            </p>
          ) : (
            !result.hits.length && <p>No matching eligible evidence.</p>
          )}
          {result.hits.map((hit) => (
            <article className="note" key={`${hit.kind}:${hit.id}`}>
              <h3>{hit.title}</h3>
              <p>{hit.excerpt}</p>
              <p>
                {hit.evidence.replaceAll('_', ' ')} · similarity {hit.similarity.toFixed(3)} ·
                characters {hit.start}–{hit.end}
              </p>
              <p className="mono">
                Source {hit.kind}:{hit.id} · digest {hit.digest}
              </p>
              {hit.kind === 'note' && (
                <button onClick={() => void openNote(hit)}>Open source note</button>
              )}
              {hit.kind === 'artifact' && (
                <button
                  onClick={() => {
                    setNote(null);
                    setArtifact(hit);
                  }}
                >
                  Inspect source artifact
                </button>
              )}
              {hit.mission_id && onOpenMission && (
                <button onClick={() => onOpenMission(hit.mission_id!)}>Open source mission</button>
              )}
            </article>
          ))}
        </>
      )}
      {note && (
        <section className="note" aria-label="Source note">
          <h3>{note.title}</h3>
          <p>{note.content}</p>
          <p className="mono">{note.id}</p>
          <button onClick={() => setNote(null)}>Close source note</button>
        </section>
      )}
      {artifact && (
        <MemoryArtifact
          sourceLabel="Retrieved evidence"
          artifactId={artifact.id}
          noteTitle={`Semantic evidence: ${artifact.title}`}
          onOpenMission={onOpenMission}
          onClose={() => setArtifact(null)}
        />
      )}
    </section>
  );
}
