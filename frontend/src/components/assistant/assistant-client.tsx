"use client";

import { useAuth, useUser } from "@clerk/nextjs";
import { Pencil } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import type { PendingRequest } from "@/lib/chat-stream";
import type { Message } from "@/types/chat";

import { ChatInput } from "@/components/assistant/chat-input";
import { ChatMessages } from "@/components/assistant/chat-messages";
import { RequestConfirmationCard } from "@/components/assistant/request-confirmation-card";
import { WelcomeScreen } from "@/components/assistant/welcome-screen";
import { triggerNotificationsRefresh } from "@/hooks/use-notifications";
import { useApi } from "@/lib/api.client";
import { streamChat } from "@/lib/chat-stream";
import { getConversation } from "@/lib/conversations";

export function AssistantClient() {
  const { getToken } = useAuth();
  const { user } = useUser();
  const router = useRouter();
  const searchParams = useSearchParams();
  const api = useApi();

  const conversationParam = searchParams.get("conversation");

  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoadingConversation, setIsLoadingConversation] = useState(false);
  const [error, setError] = useState<null | string>(null);
  // Chat is locked until the employee row is confirmed to exist
  const [isRegistered, setIsRegistered] = useState(false);

  // Pending request confirmation state
  const [pendingRequest, setPendingRequest] = useState<null | PendingRequest>(
    null,
  );
  const [isSubmittingRequest, setIsSubmittingRequest] = useState(false);
  const [requestSubmitted, setRequestSubmitted] = useState(false);
  const [requestCancelled, setRequestCancelled] = useState(false);

  const conversationIdRef = useRef<null | number>(null);
  const registeredRef = useRef(false);
  const loadedConversationRef = useRef<null | number>(null);
  const isSubmittingRef = useRef(false);

  useEffect(() => {
    if (!user || registeredRef.current) return;
    registeredRef.current = true;

    void (async () => {
      try {
        const token = await getToken();
        if (!token) return;

        const res = await fetch("/api/backend/employees/me", {
          body: JSON.stringify({
            department: null,
            email: user.primaryEmailAddress?.emailAddress ?? "",
            name: user.fullName ?? user.firstName ?? "Employee",
          }),
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          method: "POST",
        });

        // 201 = created, 409 = already exists — both mean ready to chat
        if (res.ok || res.status === 409) {
          setIsRegistered(true);
          return;
        }

        const detail = await res
          .json()
          .then((j: { detail?: string }) => j.detail)
          .catch(() => undefined);
        setError(
          `Could not set up your account (${res.status}${detail ? `: ${detail}` : ""}). Please refresh.`,
        );
      } catch (err) {
        setError(
          err instanceof Error
            ? `Registration failed: ${err.message}`
            : "Could not register your account. Please refresh and try again.",
        );
      }
    })();
  }, [user, getToken]);

  // Hydrate from ?conversation=<id> when the URL changes
  useEffect(() => {
    if (!conversationParam) return;
    const id = Number(conversationParam);
    if (!Number.isInteger(id) || id <= 0) return;
    if (loadedConversationRef.current === id) return;

    loadedConversationRef.current = id;
    setIsLoadingConversation(true);
    setError(null);

    void (async () => {
      try {
        const token = await getToken();
        if (!token) throw new Error("Not authenticated");

        const data = await getConversation(id, token);

        setMessages(
          data.messages.map((m) => ({
            content: m.content,
            id: String(m.id),
            role: m.role,
          })),
        );
        conversationIdRef.current = id;
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Could not load conversation",
        );
        loadedConversationRef.current = null;
      } finally {
        setIsLoadingConversation(false);
      }
    })();
  }, [conversationParam, getToken]);

  const handleSendMessage = useCallback(
    async (content: string) => {
      setError(null);

      const userMessage: Message = {
        content,
        id: crypto.randomUUID(),
        role: "user",
      };

      const assistantId = crypto.randomUUID();
      const assistantPlaceholder: Message = {
        content: "",
        id: assistantId,
        role: "assistant",
        streaming: true,
      };

      setMessages((prev) => [...prev, userMessage, assistantPlaceholder]);
      setIsStreaming(true);

      try {
        const token = await getToken();
        if (!token) throw new Error("Not authenticated");

        // Reset any previous pending request when starting a new message
        setPendingRequest(null);
        setRequestSubmitted(false);
        setRequestCancelled(false);

        await streamChat({
          conversationId: conversationIdRef.current,
          onConversationId: (id) => {
            conversationIdRef.current = id;
          },
          onRequestConfirmation: (req) => {
            setPendingRequest(req);
          },
          onToken: (chunk) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, content: m.content + chunk } : m,
              ),
            );
          },
          question: content,
          token,
        });

        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, streaming: false } : m,
          ),
        );
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Something went wrong";
        setError(message);
        setMessages((prev) => prev.filter((m) => m.id !== assistantId));
      } finally {
        setIsStreaming(false);
      }
    },
    [getToken],
  );

  const handleNewConversation = useCallback(() => {
    conversationIdRef.current = null;
    loadedConversationRef.current = null;
    setMessages([]);
    setError(null);
    setPendingRequest(null);
    setRequestSubmitted(false);
    setRequestCancelled(false);
    // Strip ?conversation=… from the URL without reloading
    if (conversationParam) {
      router.replace("/assistant");
    }
  }, [conversationParam, router]);

  const handleSubmitRequest = useCallback(async () => {
    if (!pendingRequest || isSubmittingRef.current) return;
    isSubmittingRef.current = true;
    setIsSubmittingRequest(true);
    try {
      await api.createRequest({
        body: pendingRequest.body,
        type: pendingRequest.type,
      });
      setRequestSubmitted(true);
      triggerNotificationsRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit request");
    } finally {
      isSubmittingRef.current = false;
      setIsSubmittingRequest(false);
    }
  }, [pendingRequest, api]);

  const handleCancelRequest = useCallback(() => {
    setRequestCancelled(true);
  }, []);

  const handleDismissRequest = useCallback(() => {
    setPendingRequest(null);
    setRequestSubmitted(false);
    setRequestCancelled(false);
  }, []);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex shrink-0 items-center justify-between border-b border-border px-5 py-2.5">
        <div className="flex items-center gap-2">
          <span
            className={`h-2 w-2 rounded-full ${isStreaming ? "animate-pulse bg-brand-teal-400" : "bg-brand-teal-400"}`}
          />
          <span className="text-[13px] font-semibold text-foreground">
            {messages.length === 0 ? "New conversation" : "Conversation"}
          </span>
        </div>
        <button
          aria-label="New conversation"
          className="flex h-7 w-7 items-center justify-center rounded-lg border border-border text-muted-foreground transition-colors hover:border-brand-purple-200 hover:text-brand-purple-600 dark:hover:border-brand-purple-700 dark:hover:text-brand-purple-400"
          onClick={handleNewConversation}
          type="button"
        >
          <Pencil className="h-3.5 w-3.5" />
        </button>
      </div>

      {isLoadingConversation ? (
        <div className="flex flex-1 items-center justify-center px-6 py-8">
          <p className="text-sm text-muted-foreground">Loading conversation…</p>
        </div>
      ) : messages.length === 0 ? (
        <div className="flex flex-1 items-center justify-center overflow-y-auto px-6 py-8">
          <WelcomeScreen onSelectPrompt={handleSendMessage} />
        </div>
      ) : (
        <div className="flex flex-1 flex-col items-center overflow-y-auto px-6 py-8">
          <ChatMessages messages={messages} />
        </div>
      )}

      {pendingRequest && (
        <div className="shrink-0 px-5 pb-3">
          <RequestConfirmationCard
            cancelled={requestCancelled}
            isSubmitting={isSubmittingRequest}
            onCancel={handleCancelRequest}
            onDismiss={handleDismissRequest}
            onSubmit={() => void handleSubmitRequest()}
            request={pendingRequest}
            submitted={requestSubmitted}
          />
        </div>
      )}

      {error && (
        <p className="shrink-0 px-5 pb-1 text-center text-[12px] text-destructive">
          {error}
        </p>
      )}

      <ChatInput
        disabled={isStreaming || !isRegistered || isLoadingConversation}
        onSendMessage={handleSendMessage}
      />
    </div>
  );
}
