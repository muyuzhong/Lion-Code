import { AssistantRuntimeProvider, useLocalRuntime } from "@assistant-ui/react";
import { Thread } from "./components/assistant-ui/thread";
import { ThreadListSidebar } from "./components/assistant-ui/threadlist-sidebar";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "./components/ui/sidebar";
import { Upload } from "lucide-react";
import { Button } from "./components/ui/button";

export default function App() {
  const runtime = useLocalRuntime({
    async *run() {
      yield {
        content: [{ type: "text", text: "Hello! I am ready to help you." }],
      };
    },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <SidebarProvider defaultOpen={true}>
        <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
          {/* 左侧侧边栏 */}
          <ThreadListSidebar />

          {/* 右侧主工作区 */}
          <SidebarInset className="flex flex-col h-full overflow-hidden">
            {/* 顶栏 Header */}
            <header className="flex h-14 shrink-0 items-center justify-between border-b px-4 bg-background">
              <div className="flex items-center gap-2">
                <SidebarTrigger className="-ml-1" />
                <span className="text-sm font-medium text-foreground">
                  New Chat
                </span>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="size-8 text-muted-foreground hover:text-foreground cursor-pointer"
                aria-label="Share chat"
              >
                <Upload className="size-4" />
              </Button>
            </header>

            {/* 聊天主视口与居中 Welcome 状态 */}
            <div className="min-h-0 flex-1 overflow-hidden">
              <Thread />
            </div>
          </SidebarInset>
        </div>
      </SidebarProvider>
    </AssistantRuntimeProvider>
  );
}
