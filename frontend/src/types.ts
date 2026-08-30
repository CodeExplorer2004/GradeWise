export interface UserInfo {
  id: number
  username: string
  role: 'student' | 'subject_teacher' | 'head_teacher' | 'academic_admin'
  school_id: number
  display_name: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: UserInfo
}

export interface ChartSpec {
  type: 'bar' | 'line' | 'radar' | 'pie' | 'none'
  title: string
  option: Record<string, unknown>
}

export interface AchievementSubject {
  subject_name: string
  score: number
  max_score: number
  pass_score: number
  passed: boolean
}

export interface AchievementExam {
  exam_name: string
  exam_date: string
  subjects: AchievementSubject[]
  total_score: number
  total_max_score: number
  passed_subjects: number
  subject_count: number
  class_rank?: number | null
  class_size?: number | null
  grade_rank?: number | null
  grade_size?: number | null
}

export interface StudentAchievementOverview {
  student_name: string
  class_name: string
  grade_level: string
  scope_label: string
  exams: AchievementExam[]
}

export interface ChatResponse {
  conversation_id: string
  answer: string
  sql?: string
  rows: Record<string, unknown>[]
  chart?: ChartSpec
  student_overview?: StudentAchievementOverview | null
  audit: Record<string, unknown>
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  sql?: string | null
  rows?: Record<string, unknown>[]
  chart?: ChartSpec | null
  student_overview?: StudentAchievementOverview | null
  allowed?: boolean | null
}

export interface ConversationSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface ConversationHistory {
  conversation_id: string
  messages: ChatMessage[]
}

export interface AnalysisScope {
  academic_year?: string | null
  grade_level?: string | null
  term?: string | null
  exam_type?: string | null
  cohort_year?: number | null
  class_name?: string | null
  subject_name?: string | null
  exam_name?: string | null
}

export interface AnalysisFilterOptions {
  academic_years: string[]
  grade_levels: string[]
  terms: string[]
  exam_types: string[]
  cohort_years: number[]
  classes: string[]
  subjects: string[]
  exams: string[]
  defaults: AnalysisScope
}

export interface DashboardData {
  average_score: number
  overall_score_rate: number
  pass_rate: number
  student_count: number
  exam_count: number
  scope_description: string
  applied_scope: AnalysisScope
  mixed_grade_scope: boolean
  mixed_academic_year_scope: boolean
  comparison_note: string
  grade_comparison: Array<{
    grade_level: string
    score_rate: number
    pass_rate: number
    student_count: number
  }>
  year_comparison: Array<{
    academic_year: string
    score_rate: number
    pass_rate: number
    student_count: number
  }>
  subject_averages: Array<{ subject_name: string; average_score: number; max_score: number }>
  exam_trend: Array<{ exam_date: string; exam_name: string; average_score: number; score_rate: number }>
}

export interface ScoreBand {
  label: string
  count: number
}

export interface LearningAlert {
  type: 'anomaly' | 'fluctuation' | 'current_risk'
  severity: 'medium' | 'high'
  student_id: number
  student_name: string
  class_name: string
  subject_name: string
  exam_name: string
  title: string
  detail: string
  current_score: number
  reference_score?: number | null
}

export interface InsightsData {
  average_score: number
  overall_score_rate: number
  pass_rate: number
  score_distribution: ScoreBand[]
  distribution_exam_name: string
  distribution_sample_size: number
  anomalies: LearningAlert[]
  fluctuations: LearningAlert[]
  current_risks: LearningAlert[]
  alert_count: number
  alert_counts: Record<'anomaly' | 'fluctuation' | 'current_risk', number>
}

export interface AlertPage {
  alert_type: 'anomaly' | 'fluctuation' | 'current_risk'
  items: LearningAlert[]
  total: number
  page: number
  page_size: number
}

export interface LearningReport {
  report_type: 'student' | 'scope_brief'
  title: string
  overview: string
  highlights: string[]
  concerns: string[]
  recommendations: string[]
  ai_comment: string
  warning_summary: string
  generated_by: 'qwen' | 'deepseek' | 'fallback'
}

export interface RiskPrediction {
  student_id: number
  class_id: number
  subject_id: number
  student_name: string
  class_name: string
  subject_name: string
  risk_score: number
  risk_level: 'low' | 'medium' | 'high'
  latest_score: number
  trend: number
  volatility: number
  failure_ratio: number
  exam_count: number
  reasons: string[]
}

export interface RiskSummary {
  model_version: string
  disclaimer: string
  predictions: RiskPrediction[]
  high_count: number
  medium_count: number
}

export interface ImportResult {
  batch_id: string
  filename: string
  source_type: 'csv' | 'xlsx' | 'json'
  total_rows: number
  accepted_rows: number
  rejected_rows: number
  inserted_rows: number
  updated_rows: number
  errors: Array<{ row: number; reason: string }>
}

export interface AgentTask {
  task_id: string
  run_id: string
  task_type: 'batch_report' | 'batch_warning'
  status: string
  result?: string | null
  scope: AgentTaskScope
  created_at?: string | null
}

export interface AgentTaskScope extends AnalysisScope {}

export interface AgentTaskOptions {
  classes: string[]
  subjects: string[]
  exams: string[]
}
