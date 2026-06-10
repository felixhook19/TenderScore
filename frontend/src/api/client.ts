/**
 * Typed API client. Plain REST against the backend; the session token is
 * held in memory only (no persistent storage of credentials).
 */

import type {
  DecisionResponse,
  LoginResponse,
  Me,
  Procurement,
  QueueEntry,
  RecommendationDetail,
  SessionResponse,
} from "./types";

const BASE = "/api";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

let sessionToken: string | null = null;

export function setSessionToken(token: string | null): void {
  sessionToken = token;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (sessionToken !== null) headers["Authorization"] = `Bearer ${sessionToken}`;

  const response = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? null : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `The request failed (${response.status}).`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      // keep the generic message
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function login(email: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>("POST", "/auth/login", { email, password });
}

export function verifyTotp(
  challengeToken: string,
  code: string,
): Promise<SessionResponse> {
  return request<SessionResponse>("POST", "/auth/totp", {
    challenge_token: challengeToken,
    code,
  });
}

export function me(): Promise<Me> {
  return request<Me>("GET", "/me");
}

export function listProcurements(): Promise<Procurement[]> {
  return request<Procurement[]>("GET", "/procurements");
}

export function moderationQueue(procurementId: string): Promise<QueueEntry[]> {
  return request<QueueEntry[]>(
    "GET",
    `/procurements/${procurementId}/moderation/queue`,
  );
}

export function recommendationDetail(
  recommendationId: string,
): Promise<RecommendationDetail> {
  return request<RecommendationDetail>(
    "GET",
    `/recommendations/${recommendationId}`,
  );
}

export function moderate(
  recommendationId: string,
  action: "confirm" | "amend",
  finalScore: number | null,
  rationale: string | null,
): Promise<DecisionResponse> {
  return request<DecisionResponse>(
    "POST",
    `/recommendations/${recommendationId}/moderate`,
    {
      action,
      final_score: finalScore,
      rationale,
    },
  );
}
