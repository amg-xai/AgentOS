import { useState } from 'react';
import type { FormEvent } from 'react';
import type { Role, State } from './api';
import { label } from './api';

export interface HistoryQuery {
  query: string;
  role_id: string;
  status: Exclude<State, 'READY'> | '';
}
export const emptyHistoryQuery: HistoryQuery = { query: '', role_id: '', status: '' };
const states: HistoryQuery['status'][] = [
  'PENDING',
  'RUNNING',
  'WAITING_APPROVAL',
  'BLOCKED',
  'FAILED',
  'COMPLETED',
  'CANCELLED',
];

export function HistoryFilters({
  filters,
  roles,
  onApply,
}: {
  filters: HistoryQuery;
  roles: Role[];
  onApply: (filters: HistoryQuery) => void;
}) {
  const [draft, setDraft] = useState(filters);
  function submit(event: FormEvent) {
    event.preventDefault();
    const next = { ...draft, query: draft.query.trim(), role_id: draft.role_id.trim() };
    setDraft(next);
    onApply(next);
  }
  return (
    <form className="history-filters" aria-label="Search mission history" onSubmit={submit}>
      <label htmlFor="history-query">Search mission goals</label>
      <input
        id="history-query"
        type="search"
        maxLength={200}
        value={draft.query}
        onChange={(e) => setDraft({ ...draft, query: e.target.value })}
        placeholder="Find work across history…"
      />
      <label htmlFor="history-role">History role id</label>
      <input
        id="history-role"
        list="history-roles"
        value={draft.role_id}
        maxLength={80}
        pattern="[a-z][a-z0-9_]*"
        onChange={(e) => setDraft({ ...draft, role_id: e.target.value })}
        placeholder="All roles"
        aria-describedby="history-role-help"
      />
      <datalist id="history-roles">
        {roles.map((role) => (
          <option key={role.id} value={role.id}>
            {role.name}
          </option>
        ))}
      </datalist>
      <small id="history-role-help">Leave blank for all roles, or enter a historic role id.</small>
      <label htmlFor="history-state">Mission state</label>
      <select
        id="history-state"
        value={draft.status}
        onChange={(e) => setDraft({ ...draft, status: e.target.value as HistoryQuery['status'] })}
      >
        <option value="">All states</option>
        {states.map((state) => (
          <option key={state} value={state}>
            {label(state)}
          </option>
        ))}
      </select>
      <div className="history-filter-actions">
        <button type="submit">Apply filters</button>
        <button
          type="button"
          onClick={() => {
            setDraft(emptyHistoryQuery);
            onApply(emptyHistoryQuery);
          }}
        >
          Clear filters
        </button>
      </div>
      <p className="muted">
        Applied: goal {filters.query ? `“${filters.query}”` : 'any'} · role{' '}
        {filters.role_id || 'any'} · state {filters.status ? label(filters.status) : 'any'}.
        Overview totals remain workspace-wide.
      </p>
    </form>
  );
}
