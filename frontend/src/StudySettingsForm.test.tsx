import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test } from 'vitest';
import { StudySettingsForm } from './StudySettingsForm';
import type { StudySettings } from './api';

function Form({ disabled = false }: { disabled?: boolean }) {
  const [settings, setSettings] = useState<StudySettings | null>(null);
  return <StudySettingsForm settings={settings} onChange={setSettings} disabled={disabled} />;
}

test('planning is opt-in and resets settings when disabled', async () => {
  const user = userEvent.setup();
  render(<Form />);
  expect(screen.queryByLabelText('Available study minutes')).not.toBeInTheDocument();
  await user.click(screen.getByLabelText('Include a study plan'));
  expect(screen.getByLabelText('Available study minutes')).toHaveValue(60);
  expect(screen.getByLabelText('Maximum minutes per session')).toHaveValue(25);
  await user.clear(screen.getByLabelText('Available study minutes'));
  await user.type(screen.getByLabelText('Available study minutes'), '90');
  await user.click(screen.getByLabelText('Include a study plan'));
  await user.click(screen.getByLabelText('Include a study plan'));
  expect(screen.getByLabelText('Available study minutes')).toHaveValue(60);
});

test('read-only controls cannot enable planning', () => {
  render(<Form disabled />);
  expect(screen.getByLabelText('Include a study plan')).toBeDisabled();
});
