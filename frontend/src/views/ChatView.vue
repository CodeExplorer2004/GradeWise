<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { MessagePlugin } from 'tdesign-vue-next'
import { ArrowUpIcon, ChartLineIcon, MicrophoneIcon, SecuredIcon } from 'tdesign-icons-vue-next'
import AppShell from '@/components/AppShell.vue'
import EChart from '@/components/EChart.vue'
import { chatApi } from '@/api'
import { analysisScopeLabel, loadAnalysisScope } from '@/analysisScope'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import type { AchievementExam, AnalysisScope, StudentAchievementOverview } from '@/types'

const prompt = ref('')
const loading = ref(false)
const listening = ref(false)
const scrollTarget = ref<HTMLDivElement>()
const auth = useAuthStore()
const chat = useChatStore()
const { conversationId, messages } = storeToRefs(chat)
const analysisScope = ref<AnalysisScope>({})
const scopeLabel = computed(() => analysisScopeLabel(analysisScope.value))
const suggestions = ['各科平均分对比', '历次考试成绩趋势', '查看不及格记录']
const tableRowLimit = 100
const hiddenTableColumns = new Set([
  'school_id', 'student_id', 'class_id', 'subject_id', 'exam_id', 'score_id',
])
const columnLabels: Record<string, string> = {
  student_no: '学号',
  student_name: '学生',
  class_name: '班级',
  grade_level: '年级',
  academic_year: '学年',
  term: '学期',
  exam_date: '考试日期',
  exam_name: '考试',
  subject_code: '科目代码',
  subject_name: '科目',
  score: '成绩',
  max_score: '满分',
  pass_score: '及格线',
  passed: '结果',
  average_score: '平均分',
  score_rate: '得分率',
  pass_rate: '及格率',
  student_count: '学生数',
  exam_count: '考试数',
}

function tableColumns(rows: Record<string, unknown>[]) {
  const columns = new Set<string>()
  rows.slice(0, tableRowLimit).forEach((row) => {
    Object.keys(row).forEach((key) => {
      if (!hiddenTableColumns.has(key) && !key.endsWith('_id')) columns.add(key)
    })
  })
  return [...columns]
}

function columnLabel(key: string) {
  return columnLabels[key] || key
}

function formatTableCell(value: unknown, key: string) {
  if (value === null || value === undefined || value === '') return '—'
  if (key === 'passed' && typeof value === 'boolean') return value ? '及格' : '不及格'
  if ((key === 'score_rate' || key === 'pass_rate') && typeof value === 'number') {
    return `${Number(value.toFixed(2))}%`
  }
  return String(value)
}

function overviewSubjects(overview: StudentAchievementOverview) {
  const subjects = new Map<string, number>()
  overview.exams.forEach((exam) => {
    exam.subjects.forEach((subject) => subjects.set(subject.subject_name, subject.max_score))
  })
  return [...subjects].map(([subject_name, max_score]) => ({ subject_name, max_score }))
}

function latestOverviewExam(overview: StudentAchievementOverview) {
  return overview.exams.at(-1)
}

function subjectResult(exam: AchievementExam, subjectName: string) {
  return exam.subjects.find((subject) => subject.subject_name === subjectName)
}

function formatScore(value: number) {
  return value.toFixed(1)
}

function rankText(rank?: number | null, size?: number | null) {
  return rank && size ? `${rank}/${size}` : '—'
}

function examStatus(exam: AchievementExam) {
  const failed = exam.subject_count - exam.passed_subjects
  return failed ? `${exam.passed_subjects}科合格 / ${failed}科不合格` : `${exam.passed_subjects}科全部合格`
}

interface SpeechRecognitionEventLike extends Event {
  results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }>
}

interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: (() => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike
let recognition: SpeechRecognitionLike | null = null

function toggleVoice() {
  if (listening.value) {
    recognition?.stop()
    return
  }
  const speechWindow = window as typeof window & {
    SpeechRecognition?: SpeechRecognitionConstructor
    webkitSpeechRecognition?: SpeechRecognitionConstructor
  }
  const Recognition = speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition
  if (!Recognition) {
    MessagePlugin.warning('当前浏览器不支持语音识别，请使用最新版 Chrome 或 Edge')
    return
  }
  recognition = new Recognition()
  recognition.lang = 'zh-CN'
  recognition.continuous = false
  recognition.interimResults = true
  recognition.onresult = (event) => {
    let transcript = ''
    for (let index = 0; index < event.results.length; index += 1) {
      transcript += event.results[index][0].transcript
    }
    prompt.value = transcript.trim()
  }
  recognition.onerror = () => {
    MessagePlugin.error('语音识别失败，请检查麦克风权限')
    listening.value = false
  }
  recognition.onend = () => {
    listening.value = false
  }
  try {
    recognition.start()
    listening.value = true
  } catch {
    listening.value = false
    MessagePlugin.error('无法启动语音识别')
  }
}

async function send(suggestion?: string) {
  const content = (suggestion || prompt.value).trim()
  if (!content || loading.value) return
  chat.addMessage({ role: 'user', content })
  prompt.value = ''
  loading.value = true
  await scrollToBottom()
  try {
    const { data } = await chatApi.query(content, conversationId.value, analysisScope.value)
    chat.setConversationId(data.conversation_id, auth.user?.id)
    chat.addMessage({
      role: 'assistant',
      content: data.answer,
      sql: data.sql,
      chart: data.chart,
      rows: data.rows,
      student_overview: data.student_overview,
      allowed: Boolean(data.audit.deterministic_allowed),
    })
  } catch (error: any) {
    MessagePlugin.error(error.response?.data?.detail || '查询失败，请稍后重试')
    chat.addMessage({ role: 'assistant', content: '这次查询没有成功，请检查后端或模型服务状态。' })
  } finally {
    loading.value = false
    await scrollToBottom()
  }
}

async function scrollToBottom() {
  await nextTick()
  scrollTarget.value?.scrollTo({ top: scrollTarget.value.scrollHeight, behavior: 'smooth' })
}

function keydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
  }
}

onMounted(async () => {
  analysisScope.value = loadAnalysisScope(auth.user?.id)
  await chat.restore(auth.user?.id)
  await scrollToBottom()
})
</script>

<template>
  <AppShell>
    <div class="chat-page">
      <header class="page-header">
        <div><p class="kicker">AI QUERY</p><h1>智能问数</h1></div>
        <div class="chat-scope-state"><div class="secure-badge"><SecuredIcon /> 权限范围已锁定</div><small v-if="scopeLabel">当前分析范围：{{ scopeLabel }}</small></div>
      </header>
      <div ref="scrollTarget" class="conversation">
        <div v-for="(message, index) in messages" :key="index" class="message-row" :class="message.role">
          <div v-if="message.role === 'assistant'" class="agent-avatar">G</div>
          <article class="message-card" :class="{ 'has-results': message.rows?.length }">
            <p>{{ message.content }}</p>
            <section v-if="message.student_overview?.exams.length" class="achievement-overview">
              <header class="student-summary">
                <div class="student-identity">
                  <span class="student-avatar">{{ message.student_overview.student_name.slice(0, 1) }}</span>
                  <div><strong>{{ message.student_overview.student_name }}</strong><small>{{ message.student_overview.class_name }} · {{ message.student_overview.grade_level }}</small></div>
                </div>
                <div class="student-metrics">
                  <article>
                    <span>最近考试合格</span>
                    <strong>{{ latestOverviewExam(message.student_overview)?.passed_subjects }}/{{ latestOverviewExam(message.student_overview)?.subject_count }} 科</strong>
                    <small>{{ latestOverviewExam(message.student_overview)?.exam_name }} · {{ message.student_overview.scope_label }}</small>
                  </article>
                  <article>
                    <span>班级排名</span>
                    <strong>{{ rankText(latestOverviewExam(message.student_overview)?.class_rank, latestOverviewExam(message.student_overview)?.class_size) }}</strong>
                    <small>总分 {{ formatScore(latestOverviewExam(message.student_overview)?.total_score || 0) }} / {{ formatScore(latestOverviewExam(message.student_overview)?.total_max_score || 0) }}</small>
                  </article>
                  <article>
                    <span>年级排名</span>
                    <strong>{{ rankText(latestOverviewExam(message.student_overview)?.grade_rank, latestOverviewExam(message.student_overview)?.grade_size) }}</strong>
                    <small>{{ latestOverviewExam(message.student_overview)?.grade_rank ? '按当前可见科目统计' : '当前角色不展示' }}</small>
                  </article>
                </div>
              </header>
              <div class="achievement-table-wrap">
                <table class="achievement-table">
                  <thead><tr>
                    <th>考试名称</th>
                    <th v-for="subject in overviewSubjects(message.student_overview)" :key="subject.subject_name"><span>{{ subject.subject_name }}</span><small>满分 {{ subject.max_score }}</small></th>
                    <th><span>总分</span><small>当前可见科目</small></th>
                    <th>班级排名</th>
                    <th>状态总览</th>
                  </tr></thead>
                  <tbody><tr v-for="exam in message.student_overview.exams" :key="exam.exam_name">
                    <td class="exam-cell"><strong>{{ exam.exam_name }}</strong><small>{{ exam.exam_date }}</small></td>
                    <td v-for="subject in overviewSubjects(message.student_overview)" :key="subject.subject_name" :class="{ 'score-failed': subjectResult(exam, subject.subject_name)?.passed === false }">{{ subjectResult(exam, subject.subject_name) ? formatScore(subjectResult(exam, subject.subject_name)!.score) : '—' }}</td>
                    <td class="total-cell">{{ formatScore(exam.total_score) }}<small>/ {{ formatScore(exam.total_max_score) }}</small></td>
                    <td>{{ rankText(exam.class_rank, exam.class_size) }}</td>
                    <td><span class="exam-status" :class="{ warning: exam.passed_subjects < exam.subject_count }"><i></i>{{ examStatus(exam) }}</span></td>
                  </tr></tbody>
                </table>
              </div>
            </section>
            <div v-if="message.chart && message.chart.type !== 'none'" class="inline-chart">
              <EChart :option="message.chart.option" />
            </div>
            <div v-if="message.rows?.length" class="result-meta">
              <ChartLineIcon /> 已返回 {{ message.rows.length }} 条数据
            </div>
            <div v-if="message.rows?.length && !message.student_overview" class="result-table-wrap">
              <table class="result-table">
                <thead>
                  <tr><th v-for="column in tableColumns(message.rows)" :key="column">{{ columnLabel(column) }}</th></tr>
                </thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in message.rows.slice(0, tableRowLimit)" :key="rowIndex">
                    <td v-for="column in tableColumns(message.rows)" :key="column">{{ formatTableCell(row[column], column) }}</td>
                  </tr>
                </tbody>
              </table>
              <small v-if="message.rows.length > tableRowLimit" class="result-table-note">当前展示前 {{ tableRowLimit }} 条，共 {{ message.rows.length }} 条</small>
            </div>
            <details v-if="message.sql" class="sql-detail">
              <summary>查看已审计 SQL</summary><code>{{ message.sql }}</code>
            </details>
          </article>
        </div>
        <div v-if="loading" class="message-row assistant">
          <div class="agent-avatar">G</div><div class="message-card typing"><i></i><i></i><i></i></div>
        </div>
      </div>
      <footer class="composer-wrap">
        <div v-if="messages.length <= 1" class="suggestions">
          <button v-for="item in suggestions" :key="item" @click="send(item)">{{ item }}</button>
        </div>
        <div class="composer">
          <textarea v-model="prompt" rows="1" placeholder="询问成绩、趋势或对比分析…" @keydown="keydown"></textarea>
          <button class="voice-button" :class="{ listening }" :aria-label="listening ? '停止语音输入' : '语音输入'" @click="toggleVoice"><MicrophoneIcon /></button>
          <button class="send-button" :disabled="!prompt.trim() || loading" aria-label="发送" @click="send()"><ArrowUpIcon /></button>
        </div>
        <small>回答可能存在误差；SQL 必须通过确定性安全校验后才会执行。</small>
      </footer>
    </div>
  </AppShell>
</template>
