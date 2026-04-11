"use client"

import { useState, useRef, useEffect, useCallback, useTransition } from "react"
import { useRouter } from "next/navigation"
import { cn } from "@/lib/utils"
import { saveMessages, deleteConversation } from "../actions"
import type { MessageRow, ConversationRow } from "../actions"

const AI_URL = process.env.NEXT_PUBLIC_AI_SERVICE_URL ?? "http://localhost:8000"

const SUGGESTED = [
  "Explain my latest lab results",
  "Any concerns I should discuss with my doctor?",
  "What foods help with my current health goals?",
  "How are my key biomarkers trending?",
  "Check my medications for interactions",
]

// ─── Markdown renderer (no external dep) ─────────────────────────────────────

function SimpleMarkdown({ text }: { text: string }) {
  // Basic rendering: bold, bullets, numbered lists, inline code, paragraphs
  const lines = text.split("\n")
  const elements: React.ReactNode[] = []
  let i = 0

  function renderInline(s: string): React.ReactNode {
    const parts = s.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/)
    return parts.map((p, idx) => {
      if (p.startsWith("**") && p.endsWith("**")) return <strong key={idx}>{p.slice(2, -2)}</strong>
      if (p.startsWith("*") && p.endsWith("*")) return <em key={idx}>{p.slice(1, -1)}</em>
      if (p.startsWith("`") && p.endsWith("`")) return <code key={idx} className="rounded bg-gray-100 px-1 text-xs font-mono text-gray-800">{p.slice(1, -1)}</code>
      return p
    })
  }

  while (i < lines.length) {
    const line = lines[i]!
    if (line.match(/^#{1,3} /)) {
      const level = (line.match(/^(#+)/)?.[1] ?? "#").length
      const content = line.replace(/^#+\s/, "")
      const Tag = level === 1 ? "h3" : level === 2 ? "h4" : "h5"
      elements.push(<Tag key={i} className="mt-3 mb-1 font-semibold text-gray-900">{content}</Tag>)
    } else if (line.match(/^[-*•] /)) {
      const items: string[] = []
      while (i < lines.length && lines[i]!.match(/^[-*•] /)) {
        items.push(lines[i]!.replace(/^[-*•] /, ""))
        i++
      }
      elements.push(
        <ul key={i} className="my-1.5 ml-4 list-disc space-y-0.5 text-sm">
          {items.map((it, j) => <li key={j}>{renderInline(it)}</li>)}
        </ul>
      )
      continue
    } else if (line.match(/^\d+\. /)) {
      const items: string[] = []
      while (i < lines.length && lines[i]!.match(/^\d+\. /)) {
        items.push(lines[i]!.replace(/^\d+\. /, ""))
        i++
      }
      elements.push(
        <ol key={i} className="my-1.5 ml-4 list-decimal space-y-0.5 text-sm">
          {items.map((it, j) => <li key={j}>{renderInline(it)}</li>)}
        </ol>
      )
      continue
    } else if (line.trim() === "") {
      // skip blank
    } else {
      elements.push(<p key={i} className="text-sm leading-relaxed">{renderInline(line)}</p>)
    }
    i++
  }
  return <div className="space-y-1">{elements}</div>
}

// ─── Message bubble ───────────────────────────────────────────────────────────

function Bubble({ role, content, streaming }: { role: string; content: string; streaming?: boolean }) {
  const isUser = role === "user"
  return (
    <div className={cn("flex gap-3", isUser && "flex-row-reverse")}>
      {/* Avatar */}
      <div
        className={cn(
          "flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full text-xs font-semibold",
          isUser ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600"
        )}
      >
        {isUser ? "You" : "AI"}
      </div>

      {/* Bubble */}
      <div
        className={cn(
          "max-w-[78%] rounded-2xl px-4 py-3 text-sm",
          isUser
            ? "rounded-tr-sm bg-blue-600 text-white"
            : "rounded-tl-sm border border-gray-100 bg-white text-gray-800 shadow-sm"
        )}
      >
        {isUser ? (
          <p className="leading-relaxed">{content}</p>
        ) : (
          <>
            <SimpleMarkdown text={content} />
            {streaming && (
              <span className="mt-1 inline-flex items-center gap-0.5">
                {[0, 150, 300].map((d) => (
                  <span
                    key={d}
                    className="h-1 w-1 rounded-full bg-gray-400 animate-bounce"
                    style={{ animationDelay: `${d}ms` }}
                  />
                ))}
              </span>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ─── Main interface ───────────────────────────────────────────────────────────

export interface ChatInterfaceProps {
  conversationId: string
  userId: string
  initialMessages: MessageRow[]
  conversations: ConversationRow[]
}

export function ChatInterface({ conversationId, userId, initialMessages, conversations }: ChatInterfaceProps) {
  const router = useRouter()
  const [messages, setMessages] = useState<Array<{ role: string; content: string; id: string }>>(
    initialMessages.map((m) => ({ ...m }))
  )
  const [input, setInput] = useState("")
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [, startTransition] = useTransition()
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const send = useCallback(async (text: string) => {
    if (!text.trim() || streaming) return
    setError(null)

    const userMsg = { role: "user", content: text, id: `u-${Date.now()}` }
    const assistantMsg = { role: "assistant", content: "", id: `a-${Date.now()}` }
    setMessages((prev) => [...prev, userMsg, assistantMsg])
    setInput("")
    setStreaming(true)

    abortRef.current = new AbortController()
    let full = ""

    try {
      const res = await fetch(`${AI_URL}/chat/`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-Id": userId },
        body: JSON.stringify({ user_id: userId, conversation_id: conversationId, message: text }),
        signal: abortRef.current.signal,
      })

      if (!res.ok) {
        const errText = await res.text().catch(() => "")
        throw new Error(`AI service error ${res.status}${errText ? `: ${errText}` : ""}`)
      }

      const reader = res.body?.getReader()
      const decoder = new TextDecoder()
      if (!reader) throw new Error("No response body")

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const text = decoder.decode(value)
        for (const line of text.split("\n")) {
          if (line.startsWith("data: ")) {
            const payload = line.slice(6).trim()
            if (payload === "[DONE]") break
            try {
              const { chunk } = JSON.parse(payload) as { chunk: string }
              full += chunk
              setMessages((prev) =>
                prev.map((m) => (m.id === assistantMsg.id ? { ...m, content: full } : m))
              )
            } catch { /* skip malformed */ }
          }
        }
      }

      // Persist to DB
      const isFirst = initialMessages.length === 0
      const title = isFirst ? text.slice(0, 60) : undefined
      startTransition(async () => {
        await saveMessages(conversationId, userId, text, full, title)
      })

    } catch (e: unknown) {
      if (e instanceof Error && e.name === "AbortError") return
      const msg = e instanceof Error ? e.message : "Failed to reach AI service"
      setError(msg)
      setMessages((prev) => prev.filter((m) => m.id !== assistantMsg.id))
    } finally {
      setStreaming(false)
    }
  }, [streaming, conversationId, userId, initialMessages.length])

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      void send(input)
    }
  }

  function handleNewChat() {
    router.push("/chat")
  }

  function handleDeleteConv(id: string, e: React.MouseEvent) {
    e.preventDefault()
    startTransition(async () => {
      await deleteConversation(id)
      if (id === conversationId) router.push("/chat")
    })
  }

  const isEmpty = messages.length === 0

  return (
    <div className="flex h-[calc(100vh-88px)] overflow-hidden rounded-2xl border border-gray-100 bg-white shadow-sm">
      {/* Sidebar: conversation history */}
      <aside className="hidden w-52 flex-shrink-0 flex-col border-r border-gray-100 bg-gray-50 lg:flex">
        <div className="flex items-center justify-between px-3 py-3">
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">Chats</span>
          <button
            onClick={handleNewChat}
            className="rounded-lg p-1 text-gray-400 hover:bg-gray-200 hover:text-gray-700 transition-colors"
            title="New chat"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto space-y-0.5 px-2 pb-3">
          {conversations.map((c) => (
            <div
              key={c.id}
              className={cn(
                "group flex items-center gap-1 rounded-lg px-2 py-2 text-xs cursor-pointer transition-colors",
                c.id === conversationId
                  ? "bg-blue-50 text-blue-700 font-medium"
                  : "text-gray-600 hover:bg-gray-200"
              )}
              onClick={() => router.push(`/chat?c=${c.id}`)}
            >
              <span className="flex-1 truncate">
                {c.title ?? "New chat"}
              </span>
              <button
                onClick={(e) => handleDeleteConv(c.id, e)}
                className="hidden group-hover:block text-gray-300 hover:text-red-400 flex-shrink-0"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      </aside>

      {/* Main chat area */}
      <div className="flex flex-1 flex-col min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-3">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-blue-100">
              <svg className="h-4 w-4 text-blue-600" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
              </svg>
            </div>
            <span className="text-sm font-semibold text-gray-900">health AI</span>
          </div>
          <button
            onClick={handleNewChat}
            className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors lg:hidden"
          >
            New chat
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {isEmpty && (
            <div className="flex flex-col items-center justify-center h-full gap-6 py-10">
              <div className="text-center">
                <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-50">
                  <svg className="h-7 w-7 text-blue-500" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
                  </svg>
                </div>
                <h2 className="text-lg font-semibold text-gray-900">Ask me anything about your health</h2>
                <p className="mt-1 text-sm text-gray-500 max-w-xs mx-auto">
                  I have access to your labs, medications, and health history.
                </p>
              </div>
              <div className="grid grid-cols-1 gap-2 w-full max-w-md">
                {SUGGESTED.map((q) => (
                  <button
                    key={q}
                    onClick={() => void send(q)}
                    className="rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-left text-sm text-gray-700 shadow-sm hover:border-blue-200 hover:bg-blue-50/40 hover:text-blue-700 transition-all"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) => (
            <Bubble
              key={m.id}
              role={m.role}
              content={m.content}
              streaming={streaming && m.role === "assistant" && m.id === messages[messages.length - 1]?.id}
            />
          ))}

          {error && (
            <div className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="border-t border-gray-100 px-4 py-3">
          <div className="flex items-end gap-3 rounded-2xl border border-gray-200 bg-gray-50 px-4 py-2 focus-within:border-blue-300 focus-within:ring-2 focus-within:ring-blue-50 transition-all">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about your labs, medications, trends…"
              rows={1}
              className="flex-1 resize-none bg-transparent text-sm text-gray-900 placeholder-gray-400 outline-none max-h-32"
              style={{ minHeight: "1.5rem" }}
            />
            {streaming ? (
              <button
                onClick={() => abortRef.current?.abort()}
                className="flex-shrink-0 rounded-xl bg-red-100 p-2 text-red-500 hover:bg-red-200 transition-colors"
                title="Stop"
              >
                <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                  <rect x="6" y="6" width="12" height="12" rx="1" />
                </svg>
              </button>
            ) : (
              <button
                onClick={() => void send(input)}
                disabled={!input.trim()}
                className="flex-shrink-0 rounded-xl bg-blue-600 p-2 text-white hover:bg-blue-500 disabled:opacity-30 transition-all"
                title="Send (Enter)"
              >
                <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
                </svg>
              </button>
            )}
          </div>
          <p className="mt-1.5 text-center text-xs text-gray-300">
            health AI is not a doctor · always consult your physician for medical decisions
          </p>
        </div>
      </div>
    </div>
  )
}
