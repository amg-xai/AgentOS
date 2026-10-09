export function createRoot(): Promise<string>;
export function removeRoot(root: string): Promise<void>;
export function readSources(root: string): Promise<Uint8Array[]>;
export function startServer(root: string): Promise<{
  request(route: string, options?: RequestInit): Promise<Response>;
  fetch(input: RequestInfo | URL, options?: RequestInit): Promise<Response>;
  stop(): Promise<void>;
  observations(): Promise<{ agent: string; inputs: Record<string, unknown> }[]>;
}>;
