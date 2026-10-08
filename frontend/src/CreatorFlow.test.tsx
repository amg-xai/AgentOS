import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { App } from './App';
import { overviewFixture } from './overview-fixture';
import type { Mission } from './api';

test.each([false, true])(
  'Creator content review, retry, download, and reload (demo=%s)',
  async (demo) => {
    const goal = demo ? 'Fixed Creator demo brief' : 'Explain local mission history';
    let mission: Mission = {
      id: 'creator-1',
      goal,
      role_id: 'creator',
      status: 'PENDING',
      version: 1,
      created_at: '2026-10-09T00:00:00Z',
      updated_at: '2026-10-09T00:00:00Z',
      tasks: [
        {
          id: 'script',
          title: 'Draft the script for review',
          agent_id: 'creator_script',
          status: 'READY',
          attempts: 0,
          dependencies: [],
          outputs: null,
          error: null,
        },
      ],
    };
    const artifacts = [
      {
        id: 'outline',
        name: 'reviewed-outline.md',
        task_id: 'script',
        size: 30,
        sha256: 'a'.repeat(64),
      },
      { id: 'script', name: 'script.md', task_id: 'script', size: 30, sha256: 'b'.repeat(64) },
    ];
    const respond = (data: unknown) => new Response(JSON.stringify(data));
    let created = false;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string, options?: RequestInit) => {
        if (path === '/status')
          return respond({
            execution_mode: demo ? 'demo' : 'live',
            workflow_ready: false,
            provider_configured: !demo,
            workspace_configured: false,
            workspace_name: null,
            model: demo ? null : 'mocked-model',
            user_role: 'operator',
            workflows: [
              {
                role_id: 'developer',
                name: 'Developer',
                ready: false,
                reason: 'Developer setup required',
                steps: 'Investigate → patch → tests → review',
                context_notice: 'Source is sent to the model.',
                demo_goal: null,
              },
              {
                role_id: 'creator',
                name: 'Creator',
                ready: true,
                reason: '',
                steps: 'Brief → outline → script → human review',
                context_notice:
                  'Only the supplied brief and outline are sent to the configured model.',
                demo_goal: demo ? goal : null,
              },
            ],
          });
        if (path === '/overview') return respond(overviewFixture(demo ? 'demo' : 'live'));
        if (path.startsWith('/missions?')) return respond(created ? [mission] : []);
        if (path === '/workflows/creator') {
          expect(JSON.parse(options?.body as string)).toEqual({ goal });
          created = true;
          return respond(mission);
        }
        if (path.endsWith('/actions')) {
          mission = {
            ...mission,
            version: mission.version + 1,
            status: 'PENDING',
            tasks: [{ ...mission.tasks[0], status: 'READY', error: null }],
          };
          return respond(mission);
        }
        if (path === '/missions/creator-1/run') {
          if (options?.method === 'POST') {
            mission = {
              ...mission,
              version: mission.version + 2,
              status: 'WAITING_APPROVAL',
              tasks: [
                {
                  ...mission.tasks[0],
                  status: 'WAITING_APPROVAL',
                  attempts: mission.tasks[0].attempts + 1,
                  outputs: { script: '# Script\nFixture content' },
                },
              ],
            };
            return respond(mission);
          }
          return respond(null);
        }
        if (path === '/missions/creator-1') return respond(mission);
        if (path.endsWith('/approvals'))
          return respond(
            mission.status === 'WAITING_APPROVAL'
              ? [
                  {
                    id: 'content-review',
                    task_id: 'script',
                    task_attempt: mission.tasks[0].attempts,
                    payload_digest: 'content-bound',
                    payload: { artifact_refs: ['outline', 'script'] },
                    status: 'PENDING',
                  },
                ]
              : [],
          );
        if (path === '/approvals/content-review/decision') {
          const body = JSON.parse(options?.body as string);
          expect(body.expected_version).toBe(mission.version);
          expect(body.payload_digest).toBe('content-bound');
          const status = body.decision === 'approve' ? 'COMPLETED' : 'FAILED';
          mission = {
            ...mission,
            version: mission.version + 1,
            status,
            tasks: [{ ...mission.tasks[0], status }],
          };
          return respond(mission);
        }
        if (path.includes('/artifacts?')) return respond(mission.tasks[0].outputs ? artifacts : []);
        if (path.endsWith('/content'))
          return new Response(
            path.includes('/script/') ? '# Script: content fixture' : '# Outline fixture',
          );
        if (path === '/memory' && options?.method === 'POST') return respond({ id: 'note' });
        return respond([]);
      }),
    );
    const user = userEvent.setup();
    const view = render(<App />);
    const select = await screen.findByLabelText('Workflow');
    await user.selectOptions(select, 'creator');
    expect(screen.getByRole('button', { name: '+ New mission' })).toBeEnabled();
    expect(
      screen.queryByText('Finish local setup to run your first mission'),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '+ New mission' }));
    const packageSelect = screen.getByLabelText('Role package');
    await user.selectOptions(packageSelect, 'developer');
    expect(screen.getByLabelText('Workflow')).toHaveValue('developer');
    expect(screen.getByRole('button', { name: '+ New mission' })).toBeDisabled();
    await user.selectOptions(packageSelect, 'creator');
    expect(screen.getByLabelText('Workflow')).toHaveValue('creator');
    expect(screen.queryByRole('option', { name: 'Student' })).not.toBeInTheDocument();
    const input = screen.getByLabelText('What should your video script cover?');
    if (demo) {
      expect(input).toHaveValue(goal);
      expect(input).toHaveAttribute('readonly');
    } else {
      await user.type(input, goal);
      expect(screen.getByText(/Only the supplied brief and outline/)).toBeInTheDocument();
    }
    await user.click(
      screen.getByRole('button', { name: demo ? 'Create demo mission' : 'Create mission' }),
    );
    await user.click(await screen.findByRole('button', { name: 'Run mission' }));
    await screen.findByText(/Inspect the script and its reviewed outline/);
    expect(screen.queryByText('Tests passed')).not.toBeInTheDocument();
    expect(screen.queryByText(/Inspect the diff and test report/)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Inspect artifacts →' }));
    expect(await screen.findByText('# Script: content fixture')).toBeInTheDocument();
    expect(screen.getByLabelText('Result artifact')).toHaveValue('script');
    expect(screen.getByRole('link', { name: 'Download script.md' })).toHaveAttribute(
      'download',
      'script.md',
    );
    await user.click(screen.getByRole('button', { name: 'Save artifact reference to memory' }));
    await screen.findByText('Saved to workspace memory.');
    await user.click(screen.getByRole('button', { name: 'Deny result' }));
    await user.click(await screen.findByRole('tab', { name: /tasks/ }));
    await user.click(await screen.findByRole('button', { name: 'Retry task' }));
    await user.click(await screen.findByRole('button', { name: 'Run mission' }));
    await user.click(await screen.findByRole('button', { name: 'Accept result' }));
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Accept result' })).not.toBeInTheDocument(),
    );
    view.unmount();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: new RegExp(goal) }));
    await screen.findByText(demo ? 'OFFLINE DEMO CREATOR MISSION' : 'CREATOR MISSION');
    expect(screen.queryByText('Tests passed')).not.toBeInTheDocument();
  },
  15000,
);
