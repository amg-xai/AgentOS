import type { StudySettings } from './api';

export function StudySettingsForm({
  settings,
  onChange,
  disabled,
}: {
  settings: StudySettings | null;
  onChange: (settings: StudySettings | null) => void;
  disabled: boolean;
}) {
  return (
    <fieldset className="study-settings" disabled={disabled}>
      <legend>Optional study planning</legend>
      <label className="study-plan-toggle">
        <input
          type="checkbox"
          checked={settings !== null}
          onChange={(event) =>
            onChange(event.target.checked ? { total_minutes: 60, max_session_minutes: 25 } : null)
          }
        />
        Include a study plan
      </label>
      <p className="muted">
        Propose study blocks from your notes and quiz within your time budget. Review the complete
        bundle before accepting. Durations are suggested effort; no timer, calendar scheduling,
        grading, or exam-readiness verification occurs.
      </p>
      {settings && (
        <>
          <label htmlFor="study-total-minutes">Available study minutes</label>
          <input
            id="study-total-minutes"
            type="number"
            min={10}
            max={240}
            step={1}
            required
            value={Number.isFinite(settings.total_minutes) ? settings.total_minutes : ''}
            onChange={(event) =>
              onChange({ ...settings, total_minutes: event.target.valueAsNumber })
            }
          />
          <label htmlFor="study-session-minutes">Maximum minutes per session</label>
          <input
            id="study-session-minutes"
            type="number"
            min={10}
            max={60}
            step={1}
            required
            value={
              Number.isFinite(settings.max_session_minutes) ? settings.max_session_minutes : ''
            }
            onChange={(event) =>
              onChange({ ...settings, max_session_minutes: event.target.valueAsNumber })
            }
          />
        </>
      )}
    </fieldset>
  );
}
