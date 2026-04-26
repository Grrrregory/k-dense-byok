import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "light" }),
}));

vi.mock("@uiw/react-codemirror", () => ({
  default: () => <div data-testid="codemirror" />,
}));

const mockUseCustomMcps = vi.fn();
const mockUseBrowserUseSettings = vi.fn();
const mockUseChromeProfiles = vi.fn();
const mockUseChatGptStatus = vi.fn();
const mockUseChatGptLogin = vi.fn();

vi.mock("@/lib/use-settings", () => ({
  useCustomMcps: () => mockUseCustomMcps(),
  useBrowserUseSettings: () => mockUseBrowserUseSettings(),
  useChromeProfiles: () => mockUseChromeProfiles(),
  useChatGptStatus: () => mockUseChatGptStatus(),
  useChatGptLogin: (refresh: () => Promise<void>) => mockUseChatGptLogin(refresh),
}));

import { SettingsDialog } from "./settings-dialog";

function seedDefaultMocks() {
  mockUseCustomMcps.mockReturnValue({
    value: "{}",
    loading: false,
    saving: false,
    error: null,
    save: vi.fn(async () => true),
    refresh: vi.fn(),
  });
  mockUseBrowserUseSettings.mockReturnValue({
    config: { enabled: true, headed: false, profile: null, session: null },
    loading: false,
    saving: false,
    error: null,
    save: vi.fn(async () => true),
    refresh: vi.fn(),
  });
  mockUseChromeProfiles.mockReturnValue({
    profiles: [],
    loading: false,
    error: null,
    refresh: vi.fn(),
  });
  mockUseChatGptStatus.mockReturnValue({
    status: {
      authenticated: false,
      accountId: null,
      lastRefresh: null,
      modelsAvailable: 0,
      error: null,
    },
    loading: false,
    error: null,
    refresh: vi.fn(async () => {}),
  });
  mockUseChatGptLogin.mockReturnValue({
    pending: {
      loginSessionId: null,
      verificationUri: null,
      userCode: null,
      pollIntervalSeconds: 5,
    },
    loading: false,
    error: null,
    start: vi.fn(async () => true),
    poll: vi.fn(async () => "pending"),
    logout: vi.fn(async () => true),
    clearPending: vi.fn(),
  });
}

describe("SettingsDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    seedDefaultMocks();
  });

  it("renders existing tabs plus the providers tab", () => {
    render(<SettingsDialog open onOpenChange={() => {}} />);
    expect(screen.getByText("MCP Servers")).toBeInTheDocument();
    expect(screen.getByText("Browser")).toBeInTheDocument();
    expect(screen.getByText("Providers")).toBeInTheDocument();
  });

  it("shows the connect button when chatgpt is not authenticated", async () => {
    render(<SettingsDialog open onOpenChange={() => {}} />);
    await userEvent.click(screen.getByRole("tab", { name: "Providers" }));
    expect(screen.getByRole("button", { name: /connect chatgpt pro/i })).toBeInTheDocument();
  });

  it("shows connected state when chatgpt auth is available", async () => {
    mockUseChatGptStatus.mockReturnValue({
      status: {
        authenticated: true,
        accountId: "acct_123",
        lastRefresh: "2026-04-22T03:00:00Z",
        modelsAvailable: 2,
        error: null,
      },
      loading: false,
      error: null,
      refresh: vi.fn(async () => {}),
    });

    render(<SettingsDialog open onOpenChange={() => {}} />);
    await userEvent.click(screen.getByRole("tab", { name: "Providers" }));
    expect(screen.getByText(/connected to chatgpt pro/i)).toBeInTheDocument();
    expect(screen.getByText(/2 models available/i)).toBeInTheDocument();
  });
});
