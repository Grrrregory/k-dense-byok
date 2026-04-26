import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch, onProjectChange } = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  onProjectChange: vi.fn(() => () => {}),
}));

vi.mock("@/lib/projects", () => ({
  apiFetch,
  onProjectChange,
}));

import { useChatGptLogin, useChatGptStatus } from "./use-settings";

describe("useChatGptStatus", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    onProjectChange.mockClear();
  });

  it("loads chatgpt auth status", async () => {
    apiFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          authenticated: true,
          accountId: "acct_123",
          lastRefresh: "2026-04-22T03:00:00Z",
          modelsAvailable: 2,
          error: null,
        }),
        { status: 200 },
      ),
    );

    const { result } = renderHook(() => useChatGptStatus());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.status.authenticated).toBe(true);
    expect(result.current.status.modelsAvailable).toBe(2);
  });
});

describe("useChatGptLogin", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });

  it("starts and completes the login flow", async () => {
    const refreshStatus = vi.fn(async () => {});
    const dispatchSpy = vi.spyOn(window, "dispatchEvent");
    apiFetch.mockImplementation((path: string, init?: RequestInit) => {
      if (path === "/settings/chatgpt/login/start") {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              loginSessionId: "sess-1",
              verificationUri: "https://auth.openai.com/codex/device",
              userCode: "ABCD-1234",
              pollIntervalSeconds: 5,
            }),
            { status: 200 },
          ),
        );
      }
      if (path === "/settings/chatgpt/login/poll") {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              status: "authenticated",
              auth: {
                authenticated: true,
                accountId: "acct_123",
                lastRefresh: "2026-04-22T03:00:00Z",
                modelsAvailable: 2,
                error: null,
              },
            }),
            { status: 200 },
          ),
        );
      }
      if (path === "/settings/chatgpt/auth" && init?.method === "DELETE") {
        return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 }));
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    const { result } = renderHook(() => useChatGptLogin(refreshStatus));

    await act(async () => {
      await result.current.start();
    });

    expect(result.current.pending.loginSessionId).toBe("sess-1");
    expect(result.current.pending.userCode).toBe("ABCD-1234");

    await act(async () => {
      const status = await result.current.poll();
      expect(status).toBe("authenticated");
    });

    expect(refreshStatus).toHaveBeenCalled();
    expect(dispatchSpy).toHaveBeenCalled();
    expect(result.current.pending.loginSessionId).toBeNull();

    await act(async () => {
      const ok = await result.current.logout();
      expect(ok).toBe(true);
    });

    expect(refreshStatus).toHaveBeenCalledTimes(2);
    expect(dispatchSpy).toHaveBeenCalledTimes(2);
  });
});
