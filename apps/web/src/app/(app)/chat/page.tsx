import { getOrCreateConversation, listConversations } from "./actions"
import { ChatInterface } from "./_components/chat-interface"

export default async function ChatPage({
  searchParams,
}: {
  searchParams: Promise<{ c?: string }>
}) {
  const { c } = await searchParams
  const [{ conversation, messages, userId }, conversations] = await Promise.all([
    getOrCreateConversation(c),
    listConversations(),
  ])

  return (
    <ChatInterface
      conversationId={conversation.id}
      userId={userId}
      initialMessages={messages}
      conversations={conversations}
    />
  )
}
