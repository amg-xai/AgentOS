import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { App } from './App';
import { MissionDetail } from './MissionDetail';
import { MemoryArtifact } from './MemoryArtifact';
import { artifactPreview } from './api';
import { overviewFixture } from './overview-fixture';

const id = 'a'.repeat(32);
const other = 'b'.repeat(32);
const header = new Uint8Array(24);
header.set([137, 80, 78, 71, 13, 10, 26, 10]);
new DataView(header.buffer).setUint32(16, 1280);
new DataView(header.buffer).setUint32(20, 720);
const png = () => new Response(header, { headers: { 'Content-Type': 'image/png' } });
const metadata = {
  id,
  name: 'thumbnail.png',
  task_id: 'image',
  mission_id: 'content',
  media_type: 'image/png' as const,
  size: 24,
  sha256: 'c'.repeat(64),
};
const respond = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });

test.each([
  { mode: 'live', ready: true },
  { mode: 'live', ready: false },
  { mode: 'demo', ready: true },
])('thumbnail opt-in is explicit and respects readiness and demo (%j)', async ({ mode, ready }) => {
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === '/status')
      return respond({
        execution_mode: mode,
        user_role: 'operator',
        workflows: ['creator', 'student'].map((role_id) => ({
          role_id,
          name: role_id,
          ready: true,
          thumbnail_ready: ready,
          demo_goal: 'Fixed brief',
          reason: '',
          steps: 'Plan then review',
          context_notice: 'Offline UI fixture',
        })),
      });
    if (path === '/overview') return respond(overviewFixture(mode === 'demo' ? 'demo' : 'live'));
    if (path === '/workflows/creator') {
      expect(JSON.parse(options?.body as string)).toEqual({
        goal: mode === 'demo' ? 'Fixed brief' : 'Create an introduction',
        ...(mode === 'live' && ready ? { include_thumbnail: true } : {}),
      });
      return respond({ detail: 'Injected planning rejection' }, 422);
    }
    return respond([]);
  });
  vi.stubGlobal('fetch', fetchMock);
  const user = userEvent.setup();
  render(<App />);
  await screen.findByLabelText('Workflow');
  await user.click(screen.getByRole('button', { name: '+ New mission' }));
  if (mode === 'live')
    await user.type(
      screen.getByLabelText('What should your video script cover?'),
      'Create an introduction',
    );
  if (mode === 'live' && ready) {
    const checkbox = screen.getByRole('checkbox', { name: /Include a graphic thumbnail/ });
    expect(checkbox).not.toBeChecked();
    await user.click(checkbox);
    await user.selectOptions(screen.getByLabelText('Workflow'), 'student');
    await user.selectOptions(screen.getByLabelText('Workflow'), 'creator');
    expect(screen.getByRole('checkbox', { name: /Include a graphic thumbnail/ })).not.toBeChecked();
    await user.type(
      screen.getByLabelText('What should your video script cover?'),
      'Create an introduction',
    );
    await user.click(screen.getByRole('checkbox', { name: /Include a graphic thumbnail/ }));
  } else expect(screen.queryByRole('checkbox', { name: /Include a graphic thumbnail/ })).toBeNull();
  await user.click(
    screen.getByRole('button', {
      name: mode === 'demo' ? 'Create demo mission' : 'Create mission',
    }),
  );
  expect(await screen.findByText('Injected planning rejection')).toBeVisible();
});

test('current Creator v2 approval opens its PNG and keeps content review separate from tests', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      if (path === '/missions/content')
        return respond({
          id: 'content',
          goal: 'Explain AgentOS',
          role_id: 'creator',
          status: 'WAITING_APPROVAL',
          version: 8,
          planning: {
            contract_version: 2,
            planner_id: 'creator_thumbnail_planner',
            rationale: 'Include a graphic',
            constraints: [],
            objectives: { image: 'Review graphic' },
          },
          tasks: [
            {
              id: 'image',
              title: 'Graphic thumbnail',
              agent_id: 'alternate_image',
              status: 'WAITING_APPROVAL',
              attempts: 1,
              dependencies: [],
              input_bindings: {},
              outputs: { headline: 'Explain AgentOS' },
              error: null,
            },
          ],
        });
      if (path.endsWith('/approvals'))
        return respond([
          {
            id: 'review',
            task_id: 'image',
            status: 'PENDING',
            payload_digest: 'digest',
            payload: { artifact_refs: [id] },
          },
        ]);
      if (path.includes('/artifacts?')) return respond([metadata]);
      if (path.endsWith('/content')) return png();
      if (path.endsWith('/run')) return respond(null);
      return respond([]);
    }),
  );
  const user = userEvent.setup();
  render(<MissionDetail id="content" canWrite={true} onChange={async () => {}} />);
  await user.click(await screen.findByRole('button', { name: 'Inspect artifacts →' }));
  const image = await screen.findByRole('img', {
    name: 'Creator graphic thumbnail for human review',
  });
  expect(image).toHaveAttribute('src', `/artifacts/${id}/content`);
  expect(screen.getByRole('link', { name: 'Download thumbnail.png' })).toHaveAttribute(
    'download',
    'thumbnail.png',
  );
  expect(screen.getByRole('button', { name: 'Accept result' })).toBeEnabled();
  expect(screen.queryByText('Tests passed')).toBeNull();
});

test('linked PNG preview is local, accessible and rejects a stale selection', async () => {
  let release: (value: Response) => void = () => {};
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      if (path === `/artifacts/${id}`) return respond(metadata);
      if (path === `/artifacts/${id}/content`) return png();
      if (path === `/artifacts/${other}`)
        return new Promise<Response>((resolve) => {
          release = resolve;
        });
      return new Response('Current text');
    }),
  );
  const props = { noteTitle: 'Saved graphic', onClose: () => {} };
  const { rerender } = render(<MemoryArtifact artifactId={id} {...props} />);
  expect(
    await screen.findByRole('img', { name: 'Graphic thumbnail: thumbnail.png' }),
  ).toHaveAttribute('src', `/artifacts/${id}/content`);
  rerender(<MemoryArtifact artifactId={other} {...props} />);
  expect(screen.queryByRole('img')).toBeNull();
  rerender(<MemoryArtifact artifactId={id} {...props} />);
  await screen.findByRole('img');
  await act(async () =>
    release(respond({ ...metadata, id: other, name: 'other.md', media_type: 'text/markdown' })),
  );
  expect(screen.getByRole('img')).toHaveAttribute('src', `/artifacts/${id}/content`);
});

test.each(['size', 'format', 'content-type', 'integrity', 'stream-limit'])(
  'PNG preview rejects %s before rendering',
  async (damage) => {
    const invalid = new Uint8Array(header);
    if (damage === 'format') invalid[0] = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(damage === 'stream-limit' ? new Uint8Array(25) : invalid, {
            status: damage === 'integrity' ? 409 : 200,
            headers: { 'Content-Type': damage === 'content-type' ? 'image/svg+xml' : 'image/png' },
          }),
      ),
    );
    await expect(
      artifactPreview({ ...metadata, size: damage === 'size' ? 2_000_001 : 24 }),
    ).rejects.toThrow();
  },
);
