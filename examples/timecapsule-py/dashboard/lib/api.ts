import type { ActionResponse, RunData } from "./types";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 8_000);

  try {
    const response = await fetch(input, {
      ...init,
      cache: "no-store",
      signal: controller.signal,
      headers: { Accept: "application/json", ...init?.headers },
    });
    const payload = (await response.json()) as T & { error?: string };
    if (!response.ok) {
      throw new ApiError(payload.error ?? "The dashboard service returned an error.", response.status);
    }
    return payload;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("The dashboard service took too long to respond.");
    }
    if (error instanceof TypeError) {
      throw new ApiError("The dashboard service is unavailable.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function fetchRun(): Promise<RunData> {
  const data = await request<RunData>("/api/run");
  if (!data || !Array.isArray(data.futures)) {
    throw new ApiError("The saved run has an invalid shape.");
  }
  return data;
}

export function postFutureAction(futureId: string, action: "compare" | "minimize" | "regress") {
  return request<ActionResponse>(`/api/futures/${encodeURIComponent(futureId)}/${action}`, {
    method: "POST",
  });
}
