import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test } from 'vitest';
import { CreatorSources } from './CreatorSources';
import type { SourceText } from './api';

function Form({ disabled = false }: { disabled?: boolean }) {
  const [sources, setSources] = useState<SourceText[]>([]);
  return <CreatorSources sources={sources} onChange={setSources} disabled={disabled} />;
}

test('bounded sources use stable unique IDs after removal and disable at eight', async () => {
  const user = userEvent.setup();
  render(<Form />);
  for (let i = 0; i < 8; i++) await user.click(screen.getByRole('button', { name: 'Add source' }));
  expect(screen.getByRole('button', { name: 'Add source' })).toBeDisabled();
  await user.type(screen.getByLabelText('Source text (source_2)'), 'Keep this');
  await user.click(screen.getByRole('button', { name: 'Remove source_1' }));
  await user.click(screen.getByRole('button', { name: 'Add source' }));
  expect(screen.getByLabelText('Source text (source_2)')).toHaveValue('Keep this');
  expect(screen.getByLabelText('Source text (source_1)')).toHaveValue('');
});

test('read-only source controls cannot edit or add', () => {
  render(<Form disabled />);
  expect(screen.getByRole('button', { name: 'Add source' })).toBeDisabled();
});
