import type { SourceText } from './api';

export function CreatorSources({
  sources,
  onChange,
  disabled,
  purpose = 'outlining',
}: {
  sources: SourceText[];
  onChange: (sources: SourceText[]) => void;
  disabled: boolean;
  purpose?: 'outlining' | 'study summarization';
}) {
  function add() {
    let number = 1;
    while (sources.some((source) => source.id === `source_${number}`)) number++;
    onChange([...sources, { id: `source_${number}`, label: '', body: '' }]);
  }
  function update(id: string, key: 'label' | 'body', value: string) {
    onChange(sources.map((source) => (source.id === id ? { ...source, [key]: value } : source)));
  }
  return (
    <fieldset disabled={disabled}>
      <legend>Optional source text</legend>
      <p className="muted">
        Paste sources to research before {purpose}. Source text and research are sent to the
        configured model. Quotes are checked against your text; source truth and interpretations
        require human review. No websites or files are opened.
      </p>
      {sources.map((source) => (
        <div key={source.id}>
          <p>
            Source ID: <code>{source.id}</code>
          </p>
          <label htmlFor={`${source.id}-label`}>Source label ({source.id})</label>
          <input
            id={`${source.id}-label`}
            value={source.label}
            required
            maxLength={160}
            onChange={(event) => update(source.id, 'label', event.target.value)}
          />
          <label htmlFor={`${source.id}-body`}>Source text ({source.id})</label>
          <textarea
            id={`${source.id}-body`}
            value={source.body}
            required
            maxLength={12000}
            rows={5}
            onChange={(event) => update(source.id, 'body', event.target.value)}
          />
          <button
            type="button"
            onClick={() => onChange(sources.filter((item) => item.id !== source.id))}
          >
            Remove {source.id}
          </button>
        </div>
      ))}
      <p className="muted">
        {sources.length}/8 sources ·{' '}
        {sources.reduce((sum, source) => sum + [...source.body].length, 0)}/48,000 characters
      </p>
      <button type="button" disabled={sources.length >= 8} onClick={add}>
        Add source
      </button>
    </fieldset>
  );
}
