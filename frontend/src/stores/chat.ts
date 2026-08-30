import { ref } from 'vue'
import { defineStore } from 'pinia'
import { chatApi } from '@/api'
import type { ChatMessage } from '@/types'

const welcomeMessage: ChatMessage = {
  role: 'assistant',
  content: '你好，我是 GradeWise。你可以问我“各科平均分怎么样？”或“历次考试成绩趋势”。我只会查询你有权查看的数据。',
}

function conversationKey(userId: number) {
  return `gradewise:chat:current:${userId}`
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([{ ...welcomeMessage }])
  const conversationId = ref<string>()
  const restoredUserId = ref<number>()
  const restoring = ref(false)

  function reset(userId?: number) {
    messages.value = [{ ...welcomeMessage }]
    conversationId.value = undefined
    restoredUserId.value = userId
  }

  async function restore(userId?: number) {
    if (!userId) {
      reset()
      return
    }
    if (restoredUserId.value === userId) return

    reset(userId)
    restoring.value = true
    try {
      let selectedId = localStorage.getItem(conversationKey(userId)) || undefined
      if (!selectedId) {
        const { data: conversations } = await chatApi.conversations()
        selectedId = conversations[0]?.id
      }
      if (!selectedId) return

      const { data } = await chatApi.messages(selectedId)
      conversationId.value = data.conversation_id
      messages.value = [{ ...welcomeMessage }, ...data.messages]
      localStorage.setItem(conversationKey(userId), data.conversation_id)
    } catch {
      localStorage.removeItem(conversationKey(userId))
      reset(userId)
    } finally {
      restoring.value = false
    }
  }

  function setConversationId(value: string, userId?: number) {
    conversationId.value = value
    if (userId) localStorage.setItem(conversationKey(userId), value)
  }

  function addMessage(message: ChatMessage) {
    messages.value.push(message)
  }

  return { messages, conversationId, restoring, restore, setConversationId, addMessage, reset }
})
