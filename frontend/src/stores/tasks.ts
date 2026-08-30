import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { tasksApi } from '@/api'
import type { AgentTask, AgentTaskOptions, AgentTaskScope } from '@/types'

const terminalStatuses = new Set(['success', 'error', 'cancelled', 'interrupted'])

export const useTaskStore = defineStore('tasks', () => {
  const tasks = ref<AgentTask[]>([])
  const options = ref<AgentTaskOptions>({ classes: [], subjects: [], exams: [] })
  const currentTaskId = ref<string>()
  const loading = ref(false)
  const unreadCompleted = ref(0)
  const initializedUserId = ref<number>()
  let pollTimer: number | undefined

  const currentTask = computed(() =>
    tasks.value.find((item) => item.task_id === currentTaskId.value) || tasks.value[0] || null)
  const activeCount = computed(() =>
    tasks.value.filter((item) => !terminalStatuses.has(item.status)).length)

  function merge(task: AgentTask) {
    const index = tasks.value.findIndex((item) => item.task_id === task.task_id)
    if (index >= 0) tasks.value[index] = task
    else tasks.value.unshift(task)
  }

  function reset() {
    window.clearTimeout(pollTimer)
    pollTimer = undefined
    tasks.value = []
    options.value = { classes: [], subjects: [], exams: [] }
    currentTaskId.value = undefined
    unreadCompleted.value = 0
    initializedUserId.value = undefined
  }

  function schedulePoll() {
    window.clearTimeout(pollTimer)
    if (activeCount.value) pollTimer = window.setTimeout(refreshActive, 3000)
  }

  async function refreshActive() {
    const active = tasks.value.filter((item) => !terminalStatuses.has(item.status))
    await Promise.all(active.map(async (item) => {
      try {
        const previous = item.status
        const { data } = await tasksApi.status(item.task_id)
        merge(data)
        if (!terminalStatuses.has(previous) && data.status === 'success') {
          unreadCompleted.value += 1
          if ('Notification' in window && Notification.permission === 'granted') {
            new Notification('GradeWise：异步任务已完成', {
              body: data.task_type === 'batch_report' ? '批量报告已生成，可在数据看板查看。' : '批量预警已生成，可在数据看板查看。',
            })
          }
        }
      } catch {
        // A transient status error should not discard a recoverable task.
      }
    }))
    schedulePoll()
  }

  async function initialize(userId?: number) {
    if (!userId || initializedUserId.value === userId) {
      schedulePoll()
      return
    }
    if (initializedUserId.value !== userId) reset()
    initializedUserId.value = userId
    loading.value = true
    try {
      const [taskResponse, optionResponse] = await Promise.all([
        tasksApi.list(),
        tasksApi.options(),
      ])
      tasks.value = taskResponse.data
      options.value = optionResponse.data
      currentTaskId.value = tasks.value.find((item) => !terminalStatuses.has(item.status))?.task_id
        || tasks.value[0]?.task_id
      schedulePoll()
    } catch {
      initializedUserId.value = undefined
    } finally {
      loading.value = false
    }
  }

  async function start(taskType: AgentTask['task_type'], scope: AgentTaskScope) {
    loading.value = true
    try {
      const { data } = await tasksApi.start(taskType, scope)
      merge(data)
      currentTaskId.value = data.task_id
      schedulePoll()
      return data
    } finally {
      loading.value = false
    }
  }

  async function refresh(taskId: string) {
    const { data } = await tasksApi.status(taskId)
    merge(data)
    return data
  }

  async function cancel(taskId: string) {
    loading.value = true
    try {
      const { data } = await tasksApi.cancel(taskId)
      merge(data)
      schedulePoll()
      return data
    } finally {
      loading.value = false
    }
  }

  async function update(taskId: string, message: string) {
    loading.value = true
    try {
      const { data } = await tasksApi.update(taskId, message)
      merge(data)
      schedulePoll()
      return data
    } finally {
      loading.value = false
    }
  }

  function select(taskId: string) {
    currentTaskId.value = taskId
    unreadCompleted.value = 0
  }

  return {
    tasks, options, currentTaskId, currentTask, activeCount, loading, unreadCompleted,
    initialize, start, refresh, cancel, update, select, reset,
  }
})
