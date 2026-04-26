"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch, onProjectChange } from "@/lib/projects";

export interface UseCustomMcpsReturn {
  /** Raw JSON string of the user's custom MCP servers. */
  value: string;
  /** Whether the initial load is still in progress. */
  loading: boolean;
  /** Whether a save request is in flight. */
  saving: boolean;
  /** Error message from the most recent load or save, if any. */
  error: string | null;
  /** Persist new custom MCP JSON to the backend. */
  save: (json: string) => Promise<boolean>;
  /** Re-fetch the current value from the backend. */
  refresh: () => void;
}

export function useCustomMcps(): UseCustomMcpsReturn {
  const [value, setValue] = useState("{}");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchMcps = useCallback(() => {
    setLoading(true);
    setError(null);
    apiFetch(`/settings/mcps`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data) => {
        setValue(JSON.stringify(data, null, 2));
      })
      .catch((e) => setError(e.message ?? "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchMcps();
  }, [fetchMcps]);

  useEffect(() => onProjectChange(() => fetchMcps()), [fetchMcps]);

  const save = useCallback(async (json: string): Promise<boolean> => {
    setError(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(json);
    } catch {
      setError("Invalid JSON");
      return false;
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      setError("Must be a JSON object");
      return false;
    }

    setSaving(true);
    try {
      const res = await apiFetch(`/settings/mcps`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: json,
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `HTTP ${res.status}`);
      }
      setValue(JSON.stringify(parsed, null, 2));
      return true;
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
      return false;
    } finally {
      setSaving(false);
    }
  }, []);

  return { value, loading, saving, error, save, refresh: fetchMcps };
}

export interface BrowserUseConfig {
  enabled: boolean;
  headed: boolean;
  profile: string | null;
  session: string | null;
}

export const DEFAULT_BROWSER_USE_CONFIG: BrowserUseConfig = {
  enabled: true,
  headed: false,
  profile: null,
  session: null,
};

export interface UseBrowserUseSettingsReturn {
  config: BrowserUseConfig;
  loading: boolean;
  saving: boolean;
  error: string | null;
  save: (patch: Partial<BrowserUseConfig>) => Promise<boolean>;
  refresh: () => void;
}

export function useBrowserUseSettings(): UseBrowserUseSettingsReturn {
  const [config, setConfig] = useState<BrowserUseConfig>(
    DEFAULT_BROWSER_USE_CONFIG,
  );
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchConfig = useCallback(() => {
    setLoading(true);
    setError(null);
    apiFetch(`/settings/browser-use`)
      .then((r) =>
        r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)),
      )
      .then((data: { config?: Partial<BrowserUseConfig> }) => {
        setConfig({ ...DEFAULT_BROWSER_USE_CONFIG, ...(data.config ?? {}) });
      })
      .catch((e) => setError(e.message ?? "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  useEffect(() => onProjectChange(() => fetchConfig()), [fetchConfig]);

  const save = useCallback(
    async (patch: Partial<BrowserUseConfig>): Promise<boolean> => {
      setError(null);
      setSaving(true);
      const next: BrowserUseConfig = { ...config, ...patch };
      try {
        const res = await apiFetch(`/settings/browser-use`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(next),
        });
        if (!res.ok) {
          const detail = await res.text();
          throw new Error(detail || `HTTP ${res.status}`);
        }
        const data: { config?: Partial<BrowserUseConfig> } = await res
          .json()
          .catch(() => ({}));
        setConfig({ ...DEFAULT_BROWSER_USE_CONFIG, ...(data.config ?? next) });
        return true;
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Save failed");
        return false;
      } finally {
        setSaving(false);
      }
    },
    [config],
  );

  return { config, loading, saving, error, save, refresh: fetchConfig };
}

export interface ChromeProfile {
  /** Directory name under Chrome's user-data dir (passed to --profile). */
  id: string;
  /** Display name shown in Chrome (falls back to the directory name). */
  name: string;
  /** Google account email when signed-in; null otherwise. */
  email: string | null;
  /** Absolute path to the profile directory on disk. */
  path: string;
}

export interface UseChromeProfilesReturn {
  profiles: ChromeProfile[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

/**
 * Fetch Chrome profiles installed on the user's machine.
 *
 * Returns an empty array when Chrome isn't installed. The list is
 * machine-scoped, so no project-change refetch is needed.
 */
export function useChromeProfiles(): UseChromeProfilesReturn {
  const [profiles, setProfiles] = useState<ChromeProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchProfiles = useCallback(() => {
    setLoading(true);
    setError(null);
    apiFetch(`/system/chrome-profiles`)
      .then((r) =>
        r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)),
      )
      .then((data: { profiles?: ChromeProfile[] }) => {
        setProfiles(Array.isArray(data.profiles) ? data.profiles : []);
      })
      .catch((e) => setError(e.message ?? "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchProfiles();
  }, [fetchProfiles]);

  return { profiles, loading, error, refresh: fetchProfiles };
}

export interface ChatGptStatus {
  authenticated: boolean;
  accountId: string | null;
  lastRefresh: string | null;
  modelsAvailable: number;
  error: string | null;
}

export const DEFAULT_CHATGPT_STATUS: ChatGptStatus = {
  authenticated: false,
  accountId: null,
  lastRefresh: null,
  modelsAvailable: 0,
  error: null,
};

export interface UseChatGptStatusReturn {
  status: ChatGptStatus;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useChatGptStatus(): UseChatGptStatusReturn {
  const [status, setStatus] = useState<ChatGptStatus>(DEFAULT_CHATGPT_STATUS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch(`/settings/chatgpt/status`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data: Partial<ChatGptStatus> = await res.json();
      setStatus({ ...DEFAULT_CHATGPT_STATUS, ...data });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load");
      setStatus(DEFAULT_CHATGPT_STATUS);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  useEffect(
    () => onProjectChange(() => {
      void fetchStatus();
    }),
    [fetchStatus],
  );

  return { status, loading, error, refresh: fetchStatus };
}

export interface ChatGptLoginPending {
  loginSessionId: string | null;
  verificationUri: string | null;
  userCode: string | null;
  pollIntervalSeconds: number;
}

const DEFAULT_CHATGPT_LOGIN_PENDING: ChatGptLoginPending = {
  loginSessionId: null,
  verificationUri: null,
  userCode: null,
  pollIntervalSeconds: 5,
};

export interface UseChatGptLoginReturn {
  pending: ChatGptLoginPending;
  loading: boolean;
  error: string | null;
  start: () => Promise<boolean>;
  poll: () => Promise<"pending" | "authenticated" | false>;
  logout: () => Promise<boolean>;
  clearPending: () => void;
}

export function useChatGptLogin(
  refreshStatus: () => Promise<void>,
): UseChatGptLoginReturn {
  const [pending, setPending] = useState<ChatGptLoginPending>(
    DEFAULT_CHATGPT_LOGIN_PENDING,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clearPending = useCallback(() => {
    setPending(DEFAULT_CHATGPT_LOGIN_PENDING);
  }, []);

  const start = useCallback(async (): Promise<boolean> => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch(`/settings/chatgpt/login/start`, {
        method: "POST",
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setPending({
        loginSessionId: data.loginSessionId ?? null,
        verificationUri: data.verificationUri ?? null,
        userCode: data.userCode ?? null,
        pollIntervalSeconds: Number(data.pollIntervalSeconds ?? 5) || 5,
      });
      return true;
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start login");
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  const poll = useCallback(async (): Promise<"pending" | "authenticated" | false> => {
    if (!pending.loginSessionId) {
      return false;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch(`/settings/chatgpt/login/poll`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ loginSessionId: pending.loginSessionId }),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      if (data.status === "authenticated") {
        clearPending();
        await refreshStatus();
        window.dispatchEvent(new Event("kady:modelsChanged"));
        return "authenticated";
      }
      return "pending";
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to poll login");
      return false;
    } finally {
      setLoading(false);
    }
  }, [clearPending, pending.loginSessionId, refreshStatus]);

  const logout = useCallback(async (): Promise<boolean> => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch(`/settings/chatgpt/auth`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `HTTP ${res.status}`);
      }
      clearPending();
      await refreshStatus();
      window.dispatchEvent(new Event("kady:modelsChanged"));
      return true;
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to disconnect");
      return false;
    } finally {
      setLoading(false);
    }
  }, [clearPending, refreshStatus]);

  return { pending, loading, error, start, poll, logout, clearPending };
}
