"use server"

import { createClient } from "@/lib/supabase/server"
import { redirect } from "next/navigation"
import { revalidatePath } from "next/cache"

export interface ConversationRow {
  id: string
  title: string | null
  created_at: string
  updated_at: string
}

export interface MessageRow {
  id: string
  role: string
  content: string
  created_at: string
}

// ─── Conversation management ──────────────────────────────────────────────────

export async function getOrCreateConversation(conversationId?: string): Promise<{
  conversation: ConversationRow
  messages: MessageRow[]
  userId: string
}> {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const db = supabase as any

  if (conversationId) {
    const [convRes, msgRes] = await Promise.all([
      db.from("conversations").select("*").eq("id", conversationId).eq("user_id", user.id).single(),
      db.from("messages").select("id, role, content, created_at").eq("conversation_id", conversationId).order("created_at"),
    ])
    if (convRes.data) {
      return { conversation: convRes.data as ConversationRow, messages: (msgRes.data ?? []) as MessageRow[], userId: user.id }
    }
  }

  // Create new
  const { data: newConv } = await db.from("conversations").insert({
    user_id: user.id,
    context_type: "general",
  }).select("*").single()

  return { conversation: newConv as ConversationRow, messages: [], userId: user.id }
}

export async function listConversations(): Promise<ConversationRow[]> {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { data } = await (supabase as any)
    .from("conversations")
    .select("id, title, created_at, updated_at")
    .eq("user_id", user.id)
    .order("updated_at", { ascending: false })
    .limit(20)

  return (data ?? []) as ConversationRow[]
}

export async function saveMessages(
  conversationId: string,
  userId: string,
  userMsg: string,
  assistantMsg: string,
  title?: string
): Promise<void> {
  const supabase = await createClient()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const db = supabase as any

  await db.from("messages").insert([
    { conversation_id: conversationId, user_id: userId, role: "user",      content: userMsg },
    { conversation_id: conversationId, user_id: userId, role: "assistant", content: assistantMsg },
  ])

  const updates: Record<string, string> = { updated_at: new Date().toISOString() }
  if (title) updates["title"] = title

  await db.from("conversations").update(updates).eq("id", conversationId)

  revalidatePath("/chat")
}

export async function deleteConversation(id: string): Promise<void> {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  await (supabase as any).from("conversations").delete().eq("id", id).eq("user_id", user.id)
  revalidatePath("/chat")
}
