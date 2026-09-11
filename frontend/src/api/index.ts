import { http } from './http'
import type {
  ChatResponse,
  ConversationHistory,
  ConversationSummary,
  DashboardData,
  InsightsData,
  LearningReport,
  ImportResult,
  AgentTask,
  AgentTaskOptions,
  AgentTaskScope,
  AlertPage,
  RiskSummary,
  TokenResponse,
  AnalysisFilterOptions,
  AnalysisScope,
} from '@/types'

export const authApi = {
  login: (username: string, password: string) =>
    http.post<TokenResponse>('/auth/login', { username, password }),
}

export const chatApi = {
  query: (message: string, conversationId?: string, scope: AnalysisScope = {}) =>
    http.post<ChatResponse>('/chat/query', {
      message,
      conversation_id: conversationId || null,
      scope,
    }),
  conversations: () => http.get<ConversationSummary[]>('/chat/conversations'),
  messages: (conversationId: string) =>
    http.get<ConversationHistory>(`/chat/${conversationId}/messages`),
}

export const dashboardApi = {
  options: (scope: AnalysisScope = {}) =>
    http.get<AnalysisFilterOptions>('/dashboard/options', { params: scope }),
  summary: (scope: AnalysisScope = {}) =>
    http.get<DashboardData>('/dashboard/summary', { params: scope }),
}

export const insightsApi = {
  summary: (scope: AnalysisScope = {}) =>
    http.get<InsightsData>('/insights/summary', { params: scope }),
  alerts: (type: AlertPage['alert_type'], page = 1, pageSize = 20, scope: AnalysisScope = {}) =>
    http.get<AlertPage>('/insights/alerts', {
      params: { type, page, page_size: pageSize, ...scope },
    }),
}

export const reportsApi = {
  generate: (scope: AnalysisScope = {}) =>
    http.post<LearningReport>('/reports/generate', { report_type: 'auto', scope }),
}

export const risksApi = {
  summary: (scope: AnalysisScope = {}) =>
    http.get<RiskSummary>('/risks/summary', { params: scope }),
  refresh: (scope: AnalysisScope = {}) =>
    http.post<RiskSummary>('/risks/refresh', null, { params: scope }),
}

export const importsApi = {
  scores: (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return http.post<ImportResult>('/imports/scores', body)
  },
}

export const chartsApi = {
  exportSvg: (chartType: 'bar' | 'line' | 'radar' | 'pie', title: string, option: Record<string, unknown>) =>
    http.post<Blob>('/charts/export.svg', {
      chart_type: chartType,
      title,
      option,
    }, { responseType: 'blob' }),
}

export const tasksApi = {
  list: () => http.get<AgentTask[]>('/tasks'),
  options: () => http.get<AgentTaskOptions>('/tasks/options'),
  start: (taskType: AgentTask['task_type'], scope: AgentTaskScope = {}) =>
    http.post<AgentTask>('/tasks', { task_type: taskType, scope }),
  status: (taskId: string) => http.get<AgentTask>(`/tasks/${taskId}`),
  update: (taskId: string, message: string) =>
    http.post<AgentTask>(`/tasks/${taskId}/update`, { message }),
  retry: (taskId: string) => http.post<AgentTask>(`/tasks/${taskId}/retry`),
  cancel: (taskId: string) => http.delete<AgentTask>(`/tasks/${taskId}`),
}
