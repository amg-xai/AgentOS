import { useEffect, useId, useRef, useState } from 'react';
import { api, artifactPreview, errorMessage } from './api';
import type { ArtifactDetail } from './api';
import { ErrorNotice } from './components';

export function MemoryArtifact({
  artifactId,
  noteTitle,
  onClose,
  onOpenMission,
}: {
  artifactId: string;
  noteTitle: string;
  onClose: () => void;
  onOpenMission?: (id: string) => void;
}) {
  const headingId = useId();
  const panel = useRef<HTMLElement>(null);
  const [result, setResult] = useState<{ metadata: ArtifactDetail; text: string } | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setResult(null);
    setError('');
    panel.current?.focus();
    panel.current?.scrollIntoView?.({ block: 'nearest' });
    void api<ArtifactDetail>(
      `/artifacts/${encodeURIComponent(artifactId)}`,
      undefined,
      controller.signal,
    )
      .then(async (metadata) => ({
        metadata,
        text: await artifactPreview(metadata, controller.signal),
      }))
      .then(({ metadata, text }) => {
        if (!controller.signal.aborted) setResult({ metadata, text });
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(errorMessage(e));
      });
    return () => controller.abort();
  }, [artifactId]);
  return (
    <section
      className="panel memory-artifact"
      ref={panel}
      tabIndex={-1}
      aria-labelledby={headingId}
    >
      <div className="section-heading">
        <h2 id={headingId}>Linked artifact</h2>
        <button onClick={onClose}>Close preview</button>
      </div>
      <p>From note: {noteTitle}</p>
      <p className="muted mono">Artifact {artifactId}</p>
      <ErrorNotice message={error} />
      {error ? (
        <p>Artifact unavailable. Close the preview and try the reference again.</p>
      ) : !result || result.metadata.id !== artifactId ? (
        <p role="status">Verifying and loading linked artifact…</p>
      ) : (
        <>
          <h3>{result.metadata.name}</h3>
          <p className="muted">
            Task {result.metadata.task_id} · {result.metadata.size} bytes
          </p>
          <p className="muted mono">Owning mission: {result.metadata.mission_id}</p>
          {result.metadata.media_type === 'image/png' ? (
            <img
              className="thumbnail-preview"
              src={result.text}
              alt={`Graphic thumbnail: ${result.metadata.name}`}
              onError={() => setError('PNG could not be displayed or failed its integrity check.')}
            />
          ) : (
            <pre className="artifact-content">{result.text}</pre>
          )}
          <p className="muted mono hash">SHA-256 {result.metadata.sha256}</p>
          <div className="memory-artifact-actions">
            <a
              href={`/artifacts/${encodeURIComponent(artifactId)}/content`}
              download={result.metadata.name}
            >
              Download {result.metadata.name}
            </a>
            {onOpenMission && (
              <button onClick={() => onOpenMission(result.metadata.mission_id)}>
                Open owning mission
              </button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
