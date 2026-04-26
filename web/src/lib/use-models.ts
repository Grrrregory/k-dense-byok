"use client";

import { useCallback, useEffect, useState } from "react";

import staticModels from "@/data/models.json";
import type { Model } from "@/components/model-selector";
import { apiFetch, onProjectChange } from "@/lib/projects";

const OPENROUTER_MODELS = staticModels as Model[];

interface OllamaListResponse {
  available?: boolean;
  models?: Model[];
}

interface ChatGptListResponse {
  available?: boolean;
  models?: Model[];
}

export interface UseModelsReturn {
  /** Every model available to the user: static OpenRouter catalogue + live ChatGPT + live Ollama tags. */
  models: Model[];
  /** Just the ChatGPT-sourced entries, in the order returned by the backend. */
  chatgptModels: Model[];
  /** True when the backend reports ChatGPT models are available for the authenticated account. */
  chatgptAvailable: boolean;
  /** Just the Ollama-sourced entries, in the order returned by the backend. */
  ollamaModels: Model[];
  /** True when the backend was able to reach `OLLAMA_BASE_URL/api/tags`. */
  ollamaAvailable: boolean;
  /** Re-fetch the Ollama list. */
  refresh: () => void;
}

/**
 * Merge the static OpenRouter-derived `models.json` with whatever models
 * are currently pulled in the user's local Ollama server.
 *
 * Ollama discovery is best-effort: if the daemon is offline we silently
 * fall back to OpenRouter-only. The hook re-fetches on project change to
 * keep the list fresh when the user returns after pulling a new model.
 */
export function useModels(): UseModelsReturn {
  const [chatgptModels, setChatgptModels] = useState<Model[]>([]);
  const [chatgptAvailable, setChatgptAvailable] = useState(false);
  const [ollamaModels, setOllamaModels] = useState<Model[]>([]);
  const [ollamaAvailable, setOllamaAvailable] = useState(false);

  const fetchChatGpt = useCallback(() => {
    apiFetch("/chatgpt/models")
      .then((r) => (r.ok ? (r.json() as Promise<ChatGptListResponse>) : null))
      .then((data) => {
        if (!data) return;
        setChatgptAvailable(Boolean(data.available));
        setChatgptModels(Array.isArray(data.models) ? data.models : []);
      })
      .catch(() => {
        setChatgptAvailable(false);
        setChatgptModels([]);
      });
  }, []);

  const fetchOllama = useCallback(() => {
    apiFetch("/ollama/models")
      .then((r) => (r.ok ? (r.json() as Promise<OllamaListResponse>) : null))
      .then((data) => {
        if (!data) return;
        setOllamaAvailable(Boolean(data.available));
        setOllamaModels(Array.isArray(data.models) ? data.models : []);
      })
      .catch(() => {
        setOllamaAvailable(false);
        setOllamaModels([]);
      });
  }, []);

  useEffect(() => {
    fetchChatGpt();
    fetchOllama();
  }, [fetchChatGpt, fetchOllama]);

  useEffect(
    () => onProjectChange(() => {
      fetchChatGpt();
      fetchOllama();
    }),
    [fetchChatGpt, fetchOllama],
  );

  useEffect(() => {
    const handleModelsChanged = () => {
      fetchChatGpt();
      fetchOllama();
    };
    window.addEventListener("kady:modelsChanged", handleModelsChanged);
    return () => window.removeEventListener("kady:modelsChanged", handleModelsChanged);
  }, [fetchChatGpt, fetchOllama]);

  const refresh = useCallback(() => {
    fetchChatGpt();
    fetchOllama();
  }, [fetchChatGpt, fetchOllama]);

  return {
    models: [...OPENROUTER_MODELS, ...chatgptModels, ...ollamaModels],
    chatgptModels,
    chatgptAvailable,
    ollamaModels,
    ollamaAvailable,
    refresh,
  };
}
