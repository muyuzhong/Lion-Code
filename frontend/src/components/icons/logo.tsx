import React from "react";

export function DeepSeekLogo({ className = "size-5" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      <path
        d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM10.5 7.5C11.33 7.5 12 8.17 12 9C12 9.83 11.33 10.5 10.5 10.5C9.67 10.5 9 9.83 9 9C9 8.17 9.67 7.5 10.5 7.5ZM16.5 14.5C15.1 16.5 12.8 17.5 10.5 17.5C8.8 17.5 7.3 16.9 6.2 15.8C5.9 15.5 6 15 6.4 14.8C6.8 14.6 7.3 14.7 7.6 15C8.4 15.8 9.4 16.2 10.5 16.2C12.3 16.2 14.1 15.4 15.3 13.8C15.6 13.4 16.1 13.3 16.5 13.6C16.9 13.8 17 14.3 16.5 14.5Z"
        fill="currentColor"
      />
    </svg>
  );
}

export function DeepSeekHarnessLogo() {
  return (
    <div className="flex items-center gap-2">
      <DeepSeekLogo className="size-5 text-foreground" />
      <span className="font-bold text-base tracking-tight text-foreground">
        deepseek
      </span>
      <span className="bg-foreground text-background text-[10px] font-extrabold px-1.5 py-0.5 rounded tracking-wider uppercase">
        HARNESS
      </span>
    </div>
  );
}
