"use client";

import {
  ComposerAddAttachment,
  ComposerAttachments,
} from "@/components/assistant-ui/attachment";
import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  AuiIf,
  type AssistantState,
  ComposerPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  type ToolCallMessagePartComponent,
  useAuiState,
  useAui,
} from "@assistant-ui/react";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  ChevronDownIcon,
  Code2Icon,
  LightbulbIcon,
  LineChartIcon,
  MicIcon,
  PenLineIcon,
  PlusIcon,
  SparklesIcon,
  SquareIcon,
  SunMediumIcon,
} from "lucide-react";
import {
  createContext,
  useContext,
  type ComponentType,
  type FC,
} from "react";

export type ThreadComponents = {
  AssistantMessage?: ComponentType | undefined;
  Welcome?: ComponentType | undefined;
  ToolFallback?: ToolCallMessagePartComponent | undefined;
};

export type ThreadProps = {
  components?: ThreadComponents | undefined;
};

const EMPTY_COMPONENTS: ThreadComponents = {};

const ThreadComponentsContext =
  createContext<ThreadComponents>(EMPTY_COMPONENTS);

const isNewChatView = (s: AssistantState) =>
  s.thread.messages.length === 0 &&
  (!s.thread.isLoading || s.threads.isLoading);

const isHistoryLoadingView = (s: AssistantState) =>
  s.thread.messages.length === 0 &&
  s.thread.isLoading &&
  !s.thread.isDisabled &&
  !s.threads.isLoading;

const ThreadHistorySkeleton: FC = () => (
  <div
    role="status"
    className="animate-in fade-in fill-mode-both flex flex-col gap-y-6 [animation-delay:150ms] [animation-duration:200ms]"
  >
    <span className="sr-only">Loading conversation</span>
    <Skeleton className="ml-auto h-9 w-2/5 rounded-xl motion-reduce:animate-none" />
    <div className="flex flex-col gap-y-2">
      <Skeleton className="h-4 w-11/12 motion-reduce:animate-none" />
      <Skeleton className="h-4 w-4/5 motion-reduce:animate-none" />
      <Skeleton className="h-4 w-3/5 motion-reduce:animate-none" />
    </div>
  </div>
);

export const Thread: FC<ThreadProps> = ({ components = EMPTY_COMPONENTS }) => {
  const isEmpty = useAuiState(isNewChatView);

  return (
    <ThreadComponentsContext.Provider value={components}>
      <ThreadRoot isEmpty={isEmpty} />
    </ThreadComponentsContext.Provider>
  );
};

const ThreadRoot: FC<{ isEmpty: boolean }> = ({ isEmpty }) => {
  const { Welcome = ThreadWelcome } = useContext(ThreadComponentsContext);

  return (
    <ThreadPrimitive.Root
      className="aui-root aui-thread-root bg-background flex h-full flex-col"
    >
      <ThreadPrimitive.Viewport
        turnAnchor="top"
        className="relative flex flex-1 flex-col overflow-x-auto overflow-y-scroll scroll-smooth"
      >
        <div
          className={cn(
            "mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 pt-6",
            isEmpty && "justify-center my-auto",
          )}
        >
          <AuiIf condition={isNewChatView}>
            <Welcome />
          </AuiIf>
          <AuiIf condition={isHistoryLoadingView}>
            <ThreadHistorySkeleton />
          </AuiIf>

          <div className="mb-14 flex flex-col gap-y-6 empty:hidden">
            <ThreadPrimitive.Messages>
              {() => <ThreadMessage />}
            </ThreadPrimitive.Messages>
          </div>

          <ThreadPrimitive.ViewportFooter
            className={cn(
              "bg-background flex flex-col gap-4 overflow-visible pb-6",
              !isEmpty && "sticky bottom-0 mt-auto",
            )}
          >
            <ThreadScrollToBottom />
            <Composer />
            <AuiIf condition={(s) => isNewChatView(s) && s.composer.isEmpty}>
              <ThreadSuggestions />
            </AuiIf>
          </ThreadPrimitive.ViewportFooter>
        </div>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
};

const ThreadMessage: FC = () => {
  const { AssistantMessage: AssistantMessageComponent = AssistantMessage } =
    useContext(ThreadComponentsContext);
  const role = useAuiState((s) => s.message.role);

  if (role === "user") return <UserMessage />;
  return <AssistantMessageComponent />;
};

const ThreadScrollToBottom: FC = () => {
  return (
    <ThreadPrimitive.ScrollToBottom asChild>
      <TooltipIconButton
        tooltip="Scroll to bottom"
        variant="outline"
        className="absolute -top-12 z-10 self-center rounded-full p-4 disabled:invisible"
      >
        <ArrowDownIcon />
      </TooltipIconButton>
    </ThreadPrimitive.ScrollToBottom>
  );
};

const ThreadWelcome: FC = () => {
  return (
    <div className="mb-8 flex flex-col items-center px-4 text-center">
      <h1 className="text-3xl font-semibold tracking-tight text-foreground">
        How can I help you today?
      </h1>
    </div>
  );
};

const DEFAULT_SUGGESTIONS = [
  { icon: SunMediumIcon, label: "Weather", prompt: "What's the weather like today?" },
  { icon: Code2Icon, label: "Code", prompt: "Write a clean React component" },
  { icon: PenLineIcon, label: "Write", prompt: "Draft a concise update email" },
  { icon: LineChartIcon, label: "Analyze", prompt: "Analyze trade-offs between REST and WebSocket" },
  { icon: LightbulbIcon, label: "Brainstorm", prompt: "Brainstorm feature ideas for an AI coding assistant" },
];

const ThreadSuggestions: FC = () => {
  const aui = useAui();

  return (
    <div className="mt-2 flex w-full flex-wrap items-center justify-center gap-2.5 px-4">
      {DEFAULT_SUGGESTIONS.map((item, index) => {
        const Icon = item.icon;
        return (
          <Button
            key={index}
            variant="outline"
            onClick={() => {
              aui.composer.setText(item.prompt);
            }}
            className="h-9 gap-1.5 rounded-full border border-border bg-background px-4 py-2 text-xs sm:text-sm font-medium text-foreground hover:bg-muted shadow-xs transition-colors cursor-pointer"
          >
            <Icon className="size-3.5 text-muted-foreground" />
            <span>{item.label}</span>
          </Button>
        );
      })}
    </div>
  );
};

const Composer: FC = () => {
  return (
    <ComposerPrimitive.Root className="relative flex w-full flex-col">
      <div
        className="border-border focus-within:border-ring/80 focus-within:ring-1 focus-within:ring-ring/20 flex w-full cursor-text flex-col gap-2 rounded-2xl border bg-background p-3.5 shadow-xs transition-all"
      >
        <ComposerAttachments />
        <ComposerPrimitive.Input
          placeholder="Send a message... (@ to mention, / for commands)"
          className="caret-primary placeholder:text-muted-foreground/60 max-h-48 min-h-12 w-full resize-none bg-transparent px-1 py-1 text-sm sm:text-base leading-6 outline-none"
          rows={1}
          autoFocus
          enterKeyHint="send"
          aria-label="Message input"
        />
        <ComposerAction />
      </div>
    </ComposerPrimitive.Root>
  );
};

const ComposerAction: FC = () => {
  return (
    <div className="relative flex items-center justify-between pt-1">
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-7 rounded-full text-muted-foreground hover:text-foreground"
          aria-label="Add attachment"
        >
          <PlusIcon className="size-4" />
        </Button>

        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-foreground hover:bg-muted transition-colors cursor-pointer"
        >
          <SparklesIcon className="size-3.5 text-muted-foreground" />
          <span>GPT-5.6 Luna</span>
          <ChevronDownIcon className="size-3 text-muted-foreground" />
        </button>
      </div>

      <div className="flex items-center gap-2">
        <TooltipIconButton
          tooltip="Voice input"
          side="bottom"
          type="button"
          variant="ghost"
          size="icon"
          className="size-7 rounded-full text-muted-foreground hover:text-foreground"
          aria-label="Start voice input"
        >
          <MicIcon className="size-4" />
        </TooltipIconButton>

        <AuiIf condition={(s) => !s.thread.isRunning}>
          <ComposerPrimitive.Send asChild>
            <Button
              type="button"
              variant="default"
              size="icon"
              className="size-7 rounded-full bg-foreground text-background hover:bg-foreground/90 transition-colors cursor-pointer"
              aria-label="Send message"
            >
              <ArrowUpIcon className="size-4" />
            </Button>
          </ComposerPrimitive.Send>
        </AuiIf>
        <AuiIf condition={(s) => s.thread.isRunning}>
          <ComposerPrimitive.Cancel asChild>
            <Button
              type="button"
              variant="default"
              size="icon"
              className="size-7 rounded-full bg-foreground text-background hover:bg-foreground/90 transition-colors cursor-pointer"
              aria-label="Stop generating"
            >
              <SquareIcon className="size-3 fill-current" />
            </Button>
          </ComposerPrimitive.Cancel>
        </AuiIf>
      </div>
    </div>
  );
};

const MessageError: FC = () => {
  return (
    <MessagePrimitive.Error>
      <ErrorPrimitive.Root className="border-destructive bg-destructive/10 text-destructive mt-2 rounded-md border p-3 text-sm">
        <ErrorPrimitive.Message />
      </ErrorPrimitive.Root>
    </MessagePrimitive.Error>
  );
};

const AssistantMessage: FC = () => {
  return (
    <MessagePrimitive.Root className="fade-in animate-in duration-150 relative grid w-full max-w-full grid-cols-[auto_1fr] grid-rows-[auto_1fr] gap-x-3 gap-y-1">
      <div className="bg-muted text-muted-foreground flex size-7 items-center justify-center rounded-full text-xs font-semibold">
        AI
      </div>
      <div className="min-w-0 flex-1">
        <MessagePrimitive.Parts>
          {() => <DefaultMessagePart />}
        </MessagePrimitive.Parts>
        <MessageError />
      </div>
    </MessagePrimitive.Root>
  );
};

const UserMessage: FC = () => {
  return (
    <MessagePrimitive.Root className="fade-in animate-in duration-150 flex w-full justify-end">
      <div className="bg-muted text-foreground max-w-[80%] rounded-2xl px-4 py-2.5 text-sm">
        <MessagePrimitive.Parts>
          {() => <DefaultMessagePart />}
        </MessagePrimitive.Parts>
      </div>
    </MessagePrimitive.Root>
  );
};

const DefaultMessagePart: FC = () => {
  return (
    <div className="whitespace-pre-wrap leading-relaxed text-sm">
      <MessagePrimitive.Content />
    </div>
  );
};
