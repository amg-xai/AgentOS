import { useId } from 'react';
import type { Task } from './api';
import { Badge } from './components';

// Iterative traversal also handles deep graphs without exhausting the call stack.
export function dependencyStages(tasks: Task[]): Task[][] | null {
  const byId = new Map(tasks.map((task) => [task.id, task]));
  if (byId.size !== tasks.length) return null;
  const remaining = new Map<string, number>();
  const dependants = new Map<string, string[]>();
  const depths = new Map<string, number>();
  const queue: string[] = [];
  for (const task of tasks) {
    if (
      !task.id ||
      !Array.isArray(task.dependencies) ||
      new Set(task.dependencies).size !== task.dependencies.length ||
      task.dependencies.some((id) => !byId.has(id))
    )
      return null;
    remaining.set(task.id, task.dependencies.length);
    depths.set(task.id, 0);
    if (!task.dependencies.length) queue.push(task.id);
    for (const id of task.dependencies) {
      const next = dependants.get(id) ?? [];
      next.push(task.id);
      dependants.set(id, next);
    }
  }
  for (let index = 0; index < queue.length; index++) {
    const id = queue[index];
    for (const next of dependants.get(id) ?? []) {
      depths.set(next, Math.max(depths.get(next)!, depths.get(id)! + 1));
      const count = remaining.get(next)! - 1;
      remaining.set(next, count);
      if (!count) queue.push(next);
    }
  }
  if (queue.length !== tasks.length) return null;
  const stages: Task[][] = [];
  // Snapshot order is the stable tie breaker within each dependency depth.
  for (const task of tasks) (stages[depths.get(task.id)!] ??= []).push(task);
  return stages;
}

export function TaskDependencies({
  tasks,
  onInspect,
}: {
  tasks: Task[];
  onInspect: (id: string) => void;
}) {
  const headingId = useId();
  const stages = dependencyStages(tasks);
  const byId = new Map(tasks.map((task) => [task.id, task]));
  return (
    <section className="task-dependencies" aria-labelledby={headingId}>
      <h3 id={headingId}>Task dependencies</h3>
      {!tasks.length ? (
        <p className="muted">This mission has no tasks.</p>
      ) : !stages ? (
        <p className="info">
          Dependency layout unavailable: task ids or prerequisites are invalid, or the graph
          contains a cycle. Inspect the task details below.
        </p>
      ) : (
        <>
          <p className="muted">
            Stages show dependency depth. Tasks in a stage may execute sequentially. Statuses are
            recorded; a running task does not establish that a worker is active.
          </p>
          <ol className="dependency-stages" role="list" aria-label="Dependency stages">
            {stages.map((stage, index) => (
              <li key={index}>
                <h4>Stage {index + 1}</h4>
                <ul className="dependency-tasks" role="list">
                  {stage.map((task) => {
                    const prerequisites = task.dependencies.map((id) => byId.get(id)!);
                    const incomplete = prerequisites.filter((item) => item.status !== 'COMPLETED');
                    return (
                      <li key={task.id}>
                        <div className="dependency-title">
                          <button
                            className="text-button"
                            aria-label={`Inspect task ${task.title} (${task.id})`}
                            onClick={() => onInspect(task.id)}
                          >
                            {task.title} <span className="mono">({task.id})</span>
                          </button>
                          <Badge state={task.status} />
                        </div>
                        <p className="muted">Agent: {task.agent_id.replaceAll('_', ' ')}</p>
                        {!prerequisites.length ? (
                          <p>No prerequisites.</p>
                        ) : (
                          <>
                            <p>Prerequisites:</p>
                            <ul className="dependency-prerequisites">
                              {prerequisites.map((item) => (
                                <li key={item.id}>
                                  {item.title} <span className="mono">({item.id})</span>{' '}
                                  <Badge state={item.status} />
                                </li>
                              ))}
                            </ul>
                            <p>
                              {incomplete.length
                                ? `${incomplete.length} of ${prerequisites.length} prerequisites incomplete.`
                                : 'All prerequisites completed.'}
                            </p>
                          </>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
