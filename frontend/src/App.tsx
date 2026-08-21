import React, { useState, useEffect } from "react";
import { ThreadListSidebar } from "./components/assistant-ui/threadlist-sidebar";
import { Thread } from "./components/assistant-ui/thread";

export default function App() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === "light" ? "dark" : "light"));
  };

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
      {/* 左侧侧边栏 */}
      <ThreadListSidebar
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        onNewSession={() => {}}
        currentTheme={theme}
        onToggleTheme={toggleTheme}
      />

      {/* 右侧主工作区与对话流 */}
      <main className="flex-1 flex flex-col h-full min-w-0 overflow-hidden">
        <Thread />
      </main>
    </div>
  );
}
