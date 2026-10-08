import type { State } from './api';
import { label } from './api';
export function Badge({ state }: { state: State }) {
  return <span className={`badge ${state.toLowerCase()}`}>{label(state)}</span>;
}
export function ErrorNotice({ message }: { message: string }) {
  return message ? (
    <div className="error" role="alert">
      {message}
    </div>
  ) : null;
}
