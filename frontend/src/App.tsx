import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { Thread } from "./components/assistant-ui/thread";
import { ThreadListSidebar } from "./components/assistant-ui/threadlist-sidebar.radix";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "./components/ui/radix/sidebar";
import { Separator } from "./components/ui/radix/separator";

export default function App() {
  return (
    <SidebarProvider>
      <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
        <ThreadListSidebar />
        <SidebarInset>
          <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
            <SidebarTrigger />
            <Separator orientation="vertical" className="mr-2 h-4" />
            <div className="min-w-0 flex-1 flex items-center justify-between">
              <div className="text-sm font-semibold tracking-tight">Lion Code</div>
            </div>
          </header>
          <div className="min-h-0 flex-1 overflow-hidden">
            <Thread />
          </div>
        </SidebarInset>
      </div>
    </SidebarProvider>
  );
}
