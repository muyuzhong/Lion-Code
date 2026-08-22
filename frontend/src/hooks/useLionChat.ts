import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { toast } from "sonner";

import { fetchMessages } from "@/lib/api";
import { getCapability, websocketProtocols } from "@/lib/capability";
import {
  actionForInput,
  ClientAction,
  decodeServerEvent,
  initialChatProtocolState,
  PlanApprovalChoice,
  reduceChatProtocol,
} from "@/lib/chatProtocol";
import type { ChatMessage } from "@/types/chat";

export function useLionChat(sessionId?: string) {
  const [state, dispatch] = useReducer(
    reduceChatProtocol,
    initialChatProtocolState,
  );
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectEnabledRef = useRef(true);
  const historyRequestRef = useRef(0);

  const loadCanonicalHistory = useCallback(async () => {
    const requestId = ++historyRequestRef.current;
    try {
      const history = await fetchMessages();
      if (historyRequestRef.current === requestId) {
        dispatch({ type: "replace_history", messages: history });
      }
    } catch (error) {
      console.error("Failed to load canonical history:", error);
    }
  }, []);

  const connect = useCallback(() => {
    if (
      wsRef.current &&
      (wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    const capability = getCapability();
    if (!capability) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(
      `${protocol}//${window.location.host}/ws/chat`,
      websocketProtocols(capability),
    );
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      if (reconnectTimeoutRef.current !== null) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      void loadCanonicalHistory();
    };

    ws.onclose = () => {
      setIsConnected(false);
      dispatch({ type: "disconnected" });
      wsRef.current = null;
      if (reconnectEnabledRef.current) {
        reconnectTimeoutRef.current = window.setTimeout(connect, 2000);
      }
    };

    ws.onerror = () => {
      setIsConnected(false);
    };

    ws.onmessage = (message) => {
      const rejectInvalidEvent = () => {
        const protocolMessage = "服务端消息不符合 WebSocket event 契约";
        toast.error(protocolMessage);
        dispatch({
          type: "server_event",
          event: { type: "protocol_error", message: protocolMessage },
        });
      };
      try {
        const event = decodeServerEvent(JSON.parse(message.data));
        if (!event) {
          rejectInvalidEvent();
          return;
        }
        if (event.type === "notice") {
          if (event.role === "error") toast.error(event.text);
          else toast.info(event.text);
        } else if (
          event.type === "server_error" ||
          event.type === "protocol_error"
        ) {
          toast.error(event.message);
        }
        dispatch({ type: "server_event", event });
      } catch {
        rejectInvalidEvent();
      }
    };
  }, [loadCanonicalHistory]);

  useEffect(() => {
    reconnectEnabledRef.current = true;
    connect();
    return () => {
      reconnectEnabledRef.current = false;
      if (reconnectTimeoutRef.current !== null) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      wsRef.current?.close();
    };
  }, [connect]);

  useEffect(() => {
    historyRequestRef.current += 1;
    dispatch({ type: "replace_history", messages: [] });
    if (sessionId) void loadCanonicalHistory();
  }, [loadCanonicalHistory, sessionId]);

  const sendAction = useCallback((action: ClientAction): boolean => {
    const websocket = wsRef.current;
    if (!websocket || websocket.readyState !== WebSocket.OPEN) return false;
    websocket.send(JSON.stringify(action));
    return true;
  }, []);

  const sendMessage = useCallback(
    (content: string) => {
      const action = actionForInput(content);
      if (!action || !sendAction(action)) return;
      if (action.action === "prompt") {
        const userMessage: ChatMessage = {
          id: `user-${Date.now()}`,
          role: "user",
          content: action.prompt,
          createdAt: new Date().toLocaleTimeString(),
        };
        dispatch({ type: "append_user", message: userMessage });
      } else if (action.action === "continue") {
        dispatch({ type: "run_requested" });
      }
    },
    [sendAction],
  );

  const sendCommand = useCallback(
    (command: string) => sendAction({ action: "command", command }),
    [sendAction],
  );

  const sendContinue = useCallback(() => {
    if (sendAction({ action: "continue" })) {
      dispatch({ type: "run_requested" });
    }
  }, [sendAction]);

  const sendCompact = useCallback(
    () => sendAction({ action: "compact" }),
    [sendAction],
  );

  const sendSteer = useCallback(
    (prompt: string) => sendAction({ action: "steer", prompt }),
    [sendAction],
  );

  const sendFollowUp = useCallback(
    (prompt: string) => sendAction({ action: "follow_up", prompt }),
    [sendAction],
  );

  const sendCancel = useCallback(() => {
    if (sendAction({ action: "cancel" })) {
      dispatch({ type: "disconnected" });
    }
  }, [sendAction]);

  const respondConfirm = useCallback(
    (requestId: string, approved: boolean) => {
      if (
        sendAction({ action: "confirm_response", requestId, approved })
      ) {
        dispatch({ type: "clear_confirm" });
      }
    },
    [sendAction],
  );

  const respondPlanApproval = useCallback(
    (requestId: string, choice: PlanApprovalChoice, feedback?: string) => {
      if (
        sendAction({
          action: "plan_approval_response",
          requestId,
          choice,
          feedback,
        })
      ) {
        dispatch({ type: "clear_plan_approval" });
      }
    },
    [sendAction],
  );

  return {
    messages: state.messages,
    isConnected,
    isStreaming: state.isStreaming,
    confirmRequest: state.confirmRequest,
    planApprovalRequest: state.planApprovalRequest,
    queue: state.queue,
    sendMessage,
    sendCommand,
    sendContinue,
    sendCompact,
    sendSteer,
    sendFollowUp,
    sendCancel,
    respondConfirm,
    respondPlanApproval,
  };
}
