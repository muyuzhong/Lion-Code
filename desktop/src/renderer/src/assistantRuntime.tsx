import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  type AppendMessage,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type PropsWithChildren,
} from "react";
import type { ChatMessage } from "../../shared/chat";
import type { BackendBootstrap } from "./backend";
import { LionAssistantRuntimeAdapter, type LionRuntimeSnapshot } from "./lionRuntime";

interface LionRuntimeContextValue {
  adapter: LionAssistantRuntimeAdapter;
  snapshot: LionRuntimeSnapshot;
}

const LionRuntimeContext = createContext<LionRuntimeContextValue | null>(null);

export function LionRuntimeProvider({ bootstrap, children }: PropsWithChildren<{ bootstrap: BackendBootstrap }>) {
  const adapter = useMemo(() => new LionAssistantRuntimeAdapter(bootstrap), [bootstrap]);
  const snapshot = useSyncExternalStore(adapter.subscribe, adapter.getSnapshot, adapter.getSnapshot);
  const runtime = useExternalStoreRuntime({
    messages: snapshot.protocol.messages,
    convertMessage: projectLionMessage,
    isRunning: snapshot.protocol.isStreaming,
    isLoading: snapshot.transportStatus === "loading" || snapshot.transportStatus === "reconnecting",
    isSendDisabled: snapshot.transportStatus !== "connected",
    onNew: async (message) => {
      if (!adapter.sendInput(appendMessageText(message))) throw new Error("WebSocket 未连接");
    },
    onCancel: async () => {
      if (!adapter.cancel()) throw new Error("WebSocket 未连接");
    },
    unstable_capabilities: { copy: true },
  });

  useEffect(() => {
    void adapter.start();
    return () => adapter.stop();
  }, [adapter]);

  const value = useMemo(() => ({ adapter, snapshot }), [adapter, snapshot]);
  return (
    <LionRuntimeContext.Provider value={value}>
      <AssistantRuntimeProvider runtime={runtime}>{children}</AssistantRuntimeProvider>
    </LionRuntimeContext.Provider>
  );
}

export function useLionRuntime(): LionRuntimeContextValue {
  const value = useContext(LionRuntimeContext);
  if (!value) throw new Error("useLionRuntime 必须在 LionRuntimeProvider 内使用");
  return value;
}

export function projectLionMessage(message: ChatMessage): ThreadMessageLike {
  type ContentPart = Exclude<ThreadMessageLike["content"], string>[number];
  const content: ContentPart[] = [];
  if (message.reasoning) content.push({ type: "reasoning", text: message.reasoning });
  if (message.content) content.push({ type: "text", text: message.content });
  for (const tool of message.tools ?? []) {
    content.push({
      type: "tool-call",
      toolCallId: tool.id,
      toolName: tool.toolName,
      argsText: typeof tool.args === "string" ? tool.args : JSON.stringify(tool.args ?? {}),
      result: tool.result,
      isError: tool.status === "error",
    });
  }
  return {
    id: message.id,
    role: message.role,
    content,
    createdAt: parseDate(message.createdAt),
    ...(message.role === "assistant" ? {
      status: message.isStreaming
        ? { type: "running" as const }
        : message.error
          ? { type: "incomplete" as const, reason: "error" as const, error: message.error }
          : { type: "complete" as const, reason: "stop" as const },
    } : {}),
    metadata: message.reasoningDuration === undefined
      ? undefined
      : { custom: { reasoningDuration: message.reasoningDuration } },
  };
}

function appendMessageText(message: AppendMessage): string {
  return message.content
    .filter((part): part is Extract<typeof part, { type: "text" }> => part.type === "text")
    .map((part) => part.text)
    .join("")
    .trim();
}

function parseDate(value: string | null | undefined): Date | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date;
}
