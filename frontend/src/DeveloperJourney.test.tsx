import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import type { Approval, Artifact, Mission, Task } from './api';
import { App } from './App';
import { overviewFixture } from './overview-fixture';

// HTTP fixtures exercise the UI contract, not model generation or real tests.
// Backend integration tests independently run scoped Git/tests and verify restart.
function plannedWorkflow(firstRunPasses: boolean) {
  const goal = 'Fix calculator addition. Preserve all assertions and function signatures.';
  const definitions: Omit<Task, 'status' | 'attempts' | 'outputs' | 'error'>[] = [
    {
      id: 'baseline',
      title: 'Record baseline',
      agent_id: 'registered_baseline',
      dependencies: [],
      input_bindings: {},
    },
    {
      id: 'investigate',
      title: 'Investigate addition',
      agent_id: 'registered_reader',
      dependencies: [],
      input_bindings: {},
    },
    {
      id: 'fix',
      title: 'Generate scoped patch',
      agent_id: 'registered_fixer',
      dependencies: ['investigate', 'baseline'],
      input_bindings: {
        findings: { task_id: 'investigate', output_key: 'findings' },
        baseline_summary: { task_id: 'baseline', output_key: 'baseline_summary' },
      },
    },
    {
      id: 'verify',
      title: 'Test and review patch',
      agent_id: 'registered_tester',
      dependencies: ['fix', 'baseline'],
      requires_passed_tests: true,
      input_bindings: {
        diff: { task_id: 'fix', output_key: 'diff' },
        baseline_report: { task_id: 'baseline', output_key: 'baseline_report' },
      },
    },
  ];
  const tasks = definitions.map((task): Task => ({
    ...task,
    status: task.dependencies.length ? 'PENDING' : 'READY',
    attempts: 0,
    outputs: null,
    error: null,
  }));
  let mission: Mission = {
    id: 'planned',
    goal,
    role_id: 'developer',
    status: 'PENDING',
    version: 1,
    created_at: '2026-10-09T12:00:00Z',
    updated_at: '2026-10-09T12:00:00Z',
    tasks,
    planning: {
      contract_version: 2,
      planner_id: 'registered_planner',
      rationale: 'Investigate the operator, preserve the tests, and compare test outcomes.',
      constraints: ['Preserve all assertions and function signatures.'],
      objectives: Object.fromEntries(tasks.map((task) => [task.id, task.title])),
    },
  };
  let created = false;
  let attempt = 0;
  let approvals: Approval[] = [];
  const artifacts: Artifact[] = [];
  const content = new Map<string, string>();
  const baselineReport = 'Fixture baseline: 3 tests, 2 failures; exit 1.';
  const diff = 'Fixture tested diff: replace subtraction with addition.';
  const decisions: string[] = [];
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    const respond = (value: unknown, status = 200) =>
      new Response(JSON.stringify(value), { status });
    const body = options?.body ? JSON.parse(options.body as string) : null;
    if (path === '/status')
      return respond({
        execution_mode: 'live',
        user_role: 'operator',
        provider_configured: true,
        model: 'INJECTED UI FIXTURE',
        workspace_name: 'Calculator',
        workflows: [
          {
            role_id: 'developer',
            name: 'Developer',
            ready: true,
            steps: 'Plan → baseline → investigate → patch → tests → review',
            context_notice: 'Fixture context',
            demo_goal: null,
          },
        ],
      });
    if (path === '/overview') return respond(overviewFixture());
    if (path === '/roles' || path === '/agents') return respond([]);
    if (path.startsWith('/missions?')) return respond(created ? [mission] : []);
    if (path === '/workflows/developer') {
      expect(body).toEqual({ goal });
      created = true;
      return respond(mission, 201);
    }
    if (path === '/missions/planned/run' && options?.method === 'POST') {
      expect(body).toEqual({ expected_version: mission.version });
      attempt++;
      const passed = firstRunPasses || attempt > 1;
      const report = `Fixture patched attempt ${attempt}: ${passed ? '3 passed; exit 0' : '2 failed; exit 1'}.`;
      const reviewArtifacts = [
        ['tested.diff', diff],
        ['test-report.txt', report],
        ['reviewed-baseline-report.txt', baselineReport],
      ].map(([name, text]) => {
        const id = `${name}-${attempt}`;
        content.set(id, text);
        return { id, name, task_id: 'verify', sha256: 'a'.repeat(64), size: text.length };
      });
      artifacts.push(...reviewArtifacts);
      mission = {
        ...mission,
        version: mission.version + 8,
        status: 'WAITING_APPROVAL',
        tasks: mission.tasks.map((task) => ({
          ...task,
          status: task.id === 'verify' ? 'WAITING_APPROVAL' : 'COMPLETED',
          attempts: task.id === 'verify' ? attempt : 1,
          outputs:
            task.id === 'baseline'
              ? { baseline_passed: false, baseline_report: baselineReport }
              : task.id === 'verify'
                ? { passed, report }
                : task.id === 'fix'
                  ? { diff }
                  : { findings: 'Fixture investigation' },
        })),
      };
      approvals = [
        {
          id: `review-${attempt}`,
          task_id: 'verify',
          status: 'PENDING',
          task_attempt: attempt,
          payload_digest: `digest-${attempt}`,
          payload: { artifact_refs: reviewArtifacts.map((artifact) => artifact.id) },
        },
      ];
      return respond(mission);
    }
    if (path.startsWith('/approvals/') && options?.method === 'POST') {
      expect(['approve', 'deny']).toContain(body.decision);
      expect(path).toBe(`/approvals/review-${attempt}/decision`);
      expect(body).toEqual({
        expected_version: mission.version,
        payload_digest: `digest-${attempt}`,
        decision: body.decision,
      });
      if (body.decision === 'approve') expect(mission.tasks[3].outputs?.passed).toBe(true);
      decisions.push(body.decision);
      const status = body.decision === 'approve' ? 'COMPLETED' : 'FAILED';
      mission = {
        ...mission,
        status,
        version: mission.version + 1,
        tasks: mission.tasks.map((task) => (task.id === 'verify' ? { ...task, status } : task)),
      };
      approvals = [];
      return respond(mission);
    }
    if (path === '/missions/planned/tasks/verify/actions') {
      expect(body).toEqual({ expected_version: mission.version, action: 'retry' });
      mission = {
        ...mission,
        status: 'RUNNING',
        version: mission.version + 1,
        tasks: mission.tasks.map((task) =>
          task.id === 'verify' ? { ...task, status: 'READY', outputs: null, error: null } : task,
        ),
      };
      return respond(mission);
    }
    if (path === '/missions/planned') return respond(mission);
    if (path === '/missions/planned/run') return respond(null);
    if (path.endsWith('/approvals')) return respond(approvals);
    if (path.includes('/artifacts?')) return respond(artifacts);
    if (path.includes('/events?'))
      return respond([
        {
          sequence: 1,
          timestamp: mission.created_at,
          actor: 'registered_tester',
          action: 'tool_executed',
          task_id: 'verify',
          details: { tool_id: 'terminal', fixture: true },
        },
      ]);
    if (path.startsWith('/artifacts/') && path.endsWith('/content')) {
      const text = content.get(path.split('/')[2]);
      if (text === undefined) throw new Error(`Unknown fixture artifact: ${path}`);
      return new Response(text);
    }
    throw new Error(`Unexpected request in Developer journey: ${path}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  return { goal, baselineReport, diff, decisions, fetchMock };
}

test.each([true, false])(
  'planned Developer journey through review and reload (first run passes: %s)',
  async (firstRunPasses) => {
    const fixture = plannedWorkflow(firstRunPasses);
    const user = userEvent.setup();
    const view = render(<App />);
    await user.selectOptions(await screen.findByLabelText('Workflow'), 'developer');
    await user.click(await screen.findByRole('button', { name: '+ New mission' }));
    await user.click(screen.getByLabelText('What should your agents investigate and fix?'));
    await user.paste(fixture.goal);
    await user.click(screen.getByRole('button', { name: 'Create mission' }));
    await user.click(await screen.findByText('Inspect validated Developer plan'));
    expect(screen.getByText('registered_planner')).toBeVisible();
    expect(screen.getByText('Preserve all assertions and function signatures.')).toBeVisible();
    const patch = screen.getByRole('article', { name: 'Task detail: Generate scoped patch (fix)' });
    expect(within(patch).getByText('registered_fixer')).toBeVisible();
    await user.click(within(patch).getByText('Inspect dependency inputs'));
    expect(patch).toHaveTextContent(
      'baseline_summary receives baseline_summary from Record baseline (baseline)',
    );
    await user.click(within(patch).getByRole('button', { name: 'Record baseline (baseline)' }));
    expect(
      screen.getByRole('article', { name: 'Task detail: Record baseline (baseline)' }),
    ).toHaveFocus();
    expect(screen.queryByText('Tests passed')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Run mission' }));
    expect(await screen.findByText('Baseline tests failed')).toBeVisible();
    if (!firstRunPasses) {
      expect(screen.getByText('Tests failed')).toBeVisible();
      expect(screen.getByRole('button', { name: 'Accept result' })).toBeDisabled();
      await user.click(screen.getByRole('button', { name: 'Inspect artifacts →' }));
      await user.selectOptions(screen.getByLabelText('Result artifact'), 'test-report.txt-1');
      expect(await screen.findByText('Fixture patched attempt 1: 2 failed; exit 1.')).toBeVisible();
      await user.click(screen.getByRole('button', { name: 'Deny result' }));
      await user.click(screen.getByRole('tab', { name: /tasks/ }));
      await user.click(await screen.findByRole('button', { name: 'Retry task' }));
      expect(screen.queryByText('Tests passed')).not.toBeInTheDocument();
      expect(screen.queryByText('Tests failed')).not.toBeInTheDocument();
      await user.click(await screen.findByRole('button', { name: 'Run mission' }));
    }
    const attempt = firstRunPasses ? 1 : 2;
    expect(await screen.findByText('Tests passed')).toBeVisible();
    expect(screen.getByText('Baseline tests failed')).toBeVisible();
    expect(
      within(
        screen.getByRole('article', { name: 'Task detail: Test and review patch (verify)' }),
      ).getByText('waiting approval'),
    ).toBeVisible();
    expect(
      screen.getByText(
        `Review attempt ${attempt}: tested.diff, test-report.txt, reviewed-baseline-report.txt`,
      ),
    ).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Inspect artifacts →' }));
    expect(screen.getByLabelText('Result artifact')).toHaveValue(`tested.diff-${attempt}`);
    expect(await screen.findByText(fixture.diff)).toBeVisible();
    await user.selectOptions(
      screen.getByLabelText('Result artifact'),
      `test-report.txt-${attempt}`,
    );
    expect(
      await screen.findByText(`Fixture patched attempt ${attempt}: 3 passed; exit 0.`),
    ).toBeVisible();
    await user.selectOptions(
      screen.getByLabelText('Result artifact'),
      `reviewed-baseline-report.txt-${attempt}`,
    );
    expect(await screen.findByText(fixture.baselineReport)).toBeVisible();
    await user.click(screen.getByRole('tab', { name: /activity/ }));
    expect(await screen.findByText('tool executed')).toBeVisible();
    expect(screen.getByText('verify · registered_tester')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Accept result' }));
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Accept result' })).not.toBeInTheDocument(),
    );
    expect(fixture.decisions).toEqual(firstRunPasses ? ['approve'] : ['deny', 'approve']);
    const mutations = fixture.fetchMock.mock.calls.filter(
      ([, options]) => options?.method === 'POST',
    ).length;
    view.unmount();
    render(<App />);
    await user.click(
      await screen.findByRole('button', { name: new RegExp(fixture.goal.replaceAll('.', '\\.')) }),
    );
    await user.click(await screen.findByText('Inspect validated Developer plan'));
    expect(screen.getByText('registered_planner')).toBeVisible();
    expect(screen.getByText('Tests passed')).toBeVisible();
    expect(screen.getByText('Baseline tests failed')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Run mission' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Accept result' })).not.toBeInTheDocument();
    expect(
      within(
        screen.getByRole('article', { name: 'Task detail: Test and review patch (verify)' }),
      ).getByText('completed'),
    ).toBeVisible();
    await user.click(screen.getByRole('tab', { name: /artifacts/ }));
    await user.selectOptions(
      screen.getByLabelText('Result artifact'),
      `reviewed-baseline-report.txt-${attempt}`,
    );
    expect(await screen.findByText(fixture.baselineReport)).toBeVisible();
    expect(
      fixture.fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST'),
    ).toHaveLength(mutations);
  },
  15000,
);
