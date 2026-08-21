import { useCallback, useEffect, useRef, useState } from 'react';
import { ChatMessage, ConfirmRequest, PlanApprovalRequest, ToolCallItem } from '../types';

export function useLionChat(sessionId?: string) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState<ConfirmRequest | null>(null);
  const [pendingPlanApproval, setPendingPlanApproval] = useState<PlanApprovalRequest | null>(null);
  const [notices, setNotices] = useState<{ id: string; text: string; role: string }[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.port === '3000' ? '127.0.0.1:8000' : window.location.host;
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
      setIsGenerating(false);
      // 自动重连
      reconnectTimeoutRef.current = window.setTimeout(() => {
        connect();
      }, 2000);
    };

    ws.onerror = () => {
      ws.close();
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleServerEvent(data);
      } catch (err) {
        console.error('Error parsing WS message:', err);
      }
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect, sessionId]);

  const handleServerEvent = (data: any) => {
    const type = data.type;

    if (type === 'agent_start') {
      setIsGenerating(true);
      // 创建新的 Assistant 消息占位
      setMessages((prev) => [
        ...prev,
        {
          id: `msg-${Date.now()}`,
          role: 'assistant',
          content: '',
          thinking: '',
          isThinkingActive: false,
          tools: [],
          timestamp: Date.now(),
        },
      ]);
    } else if (type === 'message_update') {
      const assistantEvent = data.assistantMessageEvent || data.assistant_message_event;
      if (!assistantEvent) return;

      const eventType = assistantEvent.type;

      if (eventType === 'thinking_start') {
        setMessages((prev) => {
          if (prev.length === 0) return prev;
          const last = { ...prev[prev.length - 1] };
          last.isThinkingActive = true;
          return [...prev.slice(0, -1), last];
        });
      } else if (eventType === 'thinking_delta') {
        const delta = assistantEvent.delta || '';
        setMessages((prev) => {
          if (prev.length === 0) return prev;
          const last = { ...prev[prev.length - 1] };
          last.thinking = (last.thinking || '') + delta;
          last.isThinkingActive = true;
          return [...prev.slice(0, -1), last];
        });
      } else if (eventType === 'thinking_end') {
        setMessages((prev) => {
          if (prev.length === 0) return prev;
          const last = { ...prev[prev.length - 1] };
          last.isThinkingActive = false;
          return [...prev.slice(0, -1), last];
        });
      } else if (eventType === 'text_delta') {
        const delta = assistantEvent.delta || '';
        setMessages((prev) => {
          if (prev.length === 0) return prev;
          const last = { ...prev[prev.length - 1] };
          last.content = (last.content || '') + delta;
          return [...prev.slice(0, -1), last];
        });
      }
    } else if (type === 'tool_execution_start') {
      const toolName = data.tool_name || data.toolName || 'tool';
      const params = data.parameters || data.input || {};
      const toolId = data.tool_call_id || `tool-${Date.now()}`;

      const newTool: ToolCallItem = {
        id: toolId,
        toolName,
        parameters: params,
        status: 'running',
        timestamp: Date.now(),
      };

      setMessages((prev) => {
        if (prev.length === 0) return prev;
        const last = { ...prev[prev.length - 1] };
        last.tools = [...(last.tools || []), newTool];
        return [...prev.slice(0, -1), last];
      });
    } else if (type === 'tool_execution_end') {
      const toolId = data.tool_call_id;
      const result = typeof data.result === 'string' ? data.result : JSON.stringify(data.result, null, 2);
      const isError = Boolean(data.is_error || data.isError);

      setMessages((prev) => {
        if (prev.length === 0) return prev;
        const last = { ...prev[prev.length - 1] };
        if (last.tools && last.tools.length > 0) {
          last.tools = last.tools.map((t) => {
            if (t.id === toolId || (!toolId && t.status === 'running')) {
              return {
                ...t,
                result,
                isError,
                status: isError ? 'error' : 'success',
              };
            }
            return t;
          });
        }
        return [...prev.slice(0, -1), last];
      });
    } else if (type === 'agent_settled' || type === 'session_agent_end') {
      setIsGenerating(false);
      setMessages((prev) => {
        if (prev.length === 0) return prev;
        const last = { ...prev[prev.length - 1] };
        last.isThinkingActive = false;
        return [...prev.slice(0, -1), last];
      });
    } else if (type === 'confirm_request') {
      setPendingConfirm({
        requestId: data.request_id,
        message: data.message,
      });
    } else if (type === 'plan_approval_request') {
      setPendingPlanApproval({
        requestId: data.request_id,
        plan: data.plan,
      });
    } else if (type === 'notice') {
      const noticeItem = { id: `notice-${Date.now()}`, text: data.text, role: data.role || 'info' };
      setNotices((prev) => [...prev, noticeItem]);
      setTimeout(() => {
        setNotices((prev) => prev.filter((n) => n.id !== noticeItem.id));
      }, 4000);
    }
  };

  const sendPrompt = useCallback(
    (promptText: string) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
      const trimmed = promptText.trim();
      if (!trimmed) return;

      // 立即添加 User 消息至列表
      setMessages((prev) => [
        ...prev,
        {
          id: `msg-${Date.now()}`,
          role: 'user',
          content: trimmed,
          timestamp: Date.now(),
        },
      ]);

      wsRef.current.send(
        JSON.stringify({
          action: 'prompt',
          prompt: trimmed,
        })
      );
    },
    []
  );

  const cancelGeneration = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ action: 'cancel' }));
  }, []);

  const respondConfirm = useCallback((requestId: string, approved: boolean) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(
      JSON.stringify({
        action: 'confirm_response',
        request_id: requestId,
        approved,
      })
    );
    setPendingConfirm(null);
  }, []);

  const respondPlanApproval = useCallback(
    (requestId: string, choice: string, feedback?: string) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
      wsRef.current.send(
        JSON.stringify({
          action: 'plan_approval_response',
          request_id: requestId,
          choice,
          feedback,
        })
      );
      setPendingPlanApproval(null);
    },
    []
  );

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  return {
    messages,
    isConnected,
    isGenerating,
    pendingConfirm,
    pendingPlanApproval,
    notices,
    sendPrompt,
    cancelGeneration,
    respondConfirm,
    respondPlanApproval,
    clearMessages,
  };
}
