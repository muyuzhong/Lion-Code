import { useCallback, useEffect, useRef, useState } from "react";
import { ChatMessage, ConfirmRequest, PlanApprovalRequest, ToolCallItem } from "@/types/chat";
import { fetchMessages } from "@/lib/api";
import { toast } from "sonner";

export function useLionChat(sessionId?: string) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);
  const [planApprovalRequest, setPlanApprovalRequest] = useState<PlanApprovalRequest | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const currentMsgIdRef = useRef<string | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws/chat`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      setIsStreaming(false);
      wsRef.current = null;
      // 自动重连
      reconnectTimeoutRef.current = window.setTimeout(() => {
        connect();
      }, 2000);
    };

    ws.onerror = () => {
      setIsConnected(false);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleServerEvent(data);
      } catch (err) {
        console.error("Failed to parse incoming WebSocket message:", err);
      }
    };
  }, []);

  const handleServerEvent = (event: any) => {
    const type = event.type;

    if (type === "agent_start") {
      setIsStreaming(true);
      const assistantMsgId = `asst-${Date.now()}`;
      currentMsgIdRef.current = assistantMsgId;
      setMessages((prev) => [
        ...prev,
        {
          id: assistantMsgId,
          role: "assistant",
          content: "",
          reasoning: "",
          tools: [],
          isStreaming: true,
          createdAt: new Date().toLocaleTimeString(),
        },
      ]);
    } else if (type === "message_update") {
      const deltaEvent = event.assistantMessageEvent || event.assistant_message_event;
      if (!deltaEvent) return;

      const deltaType = deltaEvent.type;
      const targetId = currentMsgIdRef.current;

      setMessages((prev) =>
        prev.map((msg) => {
          if (msg.id !== targetId) return msg;

          if (deltaType === "thinking_delta") {
            return {
              ...msg,
              reasoning: (msg.reasoning || "") + (deltaEvent.delta || ""),
            };
          } else if (deltaType === "text_delta") {
            return {
              ...msg,
              content: msg.content + (deltaEvent.delta || ""),
            };
          }
          return msg;
        })
      );
    } else if (type === "tool_start" || (event.tool_name && type === "tool_execution_start")) {
      const toolName = event.tool_name || event.toolName || "Tool";
      const toolId = event.tool_id || `tool-${Date.now()}`;
      const args = event.parameters || event.args || {};
      const targetId = currentMsgIdRef.current;

      const newTool: ToolCallItem = {
        id: toolId,
        toolName,
        args,
        status: "running",
        expanded: false,
      };

      setMessages((prev) =>
        prev.map((msg) => {
          if (msg.id !== targetId) return msg;
          return {
            ...msg,
            tools: [...(msg.tools || []), newTool],
          };
        })
      );
    } else if (type === "tool_end" || type === "tool_execution_end") {
      const toolId = event.tool_id;
      const result = event.result || event.output || "";
      const isError = Boolean(event.error || event.is_error);
      const targetId = currentMsgIdRef.current;

      setMessages((prev) =>
        prev.map((msg) => {
          if (msg.id !== targetId) return msg;
          const updatedTools = (msg.tools || []).map((t) => {
            if (t.id === toolId || (!toolId && t.status === "running")) {
              return {
                ...t,
                status: isError ? ("error" as const) : ("completed" as const),
                result: typeof result === "object" ? JSON.stringify(result, null, 2) : String(result),
              };
            }
            return t;
          });
          return { ...msg, tools: updatedTools };
        })
      );
    } else if (type === "session_agent_end" || type === "agent_settled" || type === "agent_end") {
      setIsStreaming(false);
      const targetId = currentMsgIdRef.current;
      setMessages((prev) =>
        prev.map((msg) => (msg.id === targetId ? { ...msg, isStreaming: false } : msg))
      );
    } else if (type === "confirm_request") {
      setConfirmRequest({
        request_id: event.request_id,
        message: event.message,
      });
    } else if (type === "plan_approval_request") {
      setPlanApprovalRequest({
        request_id: event.request_id,
        plan: event.plan,
      });
    } else if (type === "notice") {
      const text = event.text || "";
      const role = event.role || "info";
      if (role === "error") {
        toast.error(text);
      } else {
        toast.info(text);
      }
    }
  };

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  // 当外部切换 session_id 时拉取历史会话消息
  useEffect(() => {
    setConfirmRequest(null);
    setPlanApprovalRequest(null);
    if (sessionId) {
      fetchMessages()
        .then((history) => {
          setMessages(history);
        })
        .catch((err) => {
          console.error("Failed to load history messages:", err);
          setMessages([]);
        });
    } else {
      setMessages([]);
    }
  }, [sessionId]);

  const sendMessage = useCallback((content: string) => {
    if (!content.trim() || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: content.trim(),
      createdAt: new Date().toLocaleTimeString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsStreaming(true);

    wsRef.current.send(
      JSON.stringify({
        action: "prompt",
        prompt: content.trim(),
      })
    );
  }, []);

  const sendCancel = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "cancel" }));
      setIsStreaming(false);
    }
  }, []);

  const respondConfirm = useCallback((requestId: string, approved: boolean) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          action: "confirm_response",
          request_id: requestId,
          approved,
        })
      );
      setConfirmRequest(null);
    }
  }, []);

  const respondPlanApproval = useCallback(
    (requestId: string, choice: "clear-and-execute" | "execute" | "manual-execute" | "keep-planning", feedback?: string) => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({
            action: "plan_approval_response",
            request_id: requestId,
            choice,
            feedback,
          })
        );
        setPlanApprovalRequest(null);
      }
    },
    []
  );

  return {
    messages,
    isConnected,
    isStreaming,
    confirmRequest,
    planApprovalRequest,
    sendMessage,
    sendCancel,
    respondConfirm,
    respondPlanApproval,
    setMessages,
  };
}
