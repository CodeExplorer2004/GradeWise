<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { MessagePlugin } from 'tdesign-vue-next'
import { ChartBarIcon, CheckCircleIcon, FileIcon, UsergroupIcon } from 'tdesign-icons-vue-next'
import AppShell from '@/components/AppShell.vue'
import EChart from '@/components/EChart.vue'
import TaskResult from '@/components/TaskResult.vue'
import { loadAnalysisScope, saveAnalysisScope } from '@/analysisScope'
import { chartsApi, dashboardApi, importsApi, insightsApi, reportsApi, risksApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useTaskStore } from '@/stores/tasks'
import type { AgentTask, AgentTaskScope, AlertPage, AnalysisFilterOptions, AnalysisScope, DashboardData, InsightsData, LearningAlert, LearningReport, RiskSummary } from '@/types'

const auth = useAuthStore()
const taskStore = useTaskStore()
const { currentTask: task, currentTaskId, tasks, options: taskOptions, loading: taskLoading } = storeToRefs(taskStore)
const loading = ref(true)
const reportLoading = ref(false)
const importLoading = ref(false)
const riskRefreshing = ref(false)
const taskUpdate = ref('')
const taskScope = reactive({ class_name: '', subject_name: '', exam_name: '' })
const filterOptions = ref<AnalysisFilterOptions>({
  academic_years: [], grade_levels: [], terms: [], exam_types: [], cohort_years: [],
  classes: [], subjects: [], exams: [], defaults: {},
})
const filterDraft = reactive({
  academic_year: '', grade_level: '', term: '', exam_type: '', cohort_year: '',
  class_name: '', subject_name: '', exam_name: '',
})
type FilterField = keyof typeof filterDraft
const defaultScope = ref<AnalysisScope>({})
const activeScope = ref<AnalysisScope>({})
const filtersReady = ref(false)
const filterOptionsLoading = ref(false)
let filterOptionRequest = 0
const report = ref<LearningReport | null>(null)
const alertsOpen = ref(false)
const alertsLoading = ref(false)
const selectedAlertType = ref<AlertPage['alert_type']>('current_risk')
const alertPage = ref<AlertPage>({
  alert_type: 'current_risk',
  items: [],
  total: 0,
  page: 1,
  page_size: 20,
})
const notificationState = ref<'unsupported' | 'off' | 'denied' | 'enabled'>('off')
const importInput = ref<HTMLInputElement>()
const data = ref<DashboardData>({
  average_score: 0,
  overall_score_rate: 0,
  pass_rate: 0,
  student_count: 0,
  exam_count: 0,
  scope_description: '',
  applied_scope: {},
  mixed_grade_scope: false,
  mixed_academic_year_scope: false,
  comparison_note: '',
  grade_comparison: [],
  year_comparison: [],
  subject_averages: [],
  exam_trend: [],
})
const insights = ref<InsightsData>({
  average_score: 0,
  overall_score_rate: 0,
  pass_rate: 0,
  score_distribution: [],
  distribution_exam_name: '',
  distribution_sample_size: 0,
  anomalies: [],
  fluctuations: [],
  current_risks: [],
  alert_count: 0,
  alert_counts: { anomaly: 0, fluctuation: 0, current_risk: 0 },
})
const risks = ref<RiskSummary>({
  model_version: 'transparent-rule-v2',
  disclaimer: '',
  predictions: [],
  high_count: 0,
  medium_count: 0,
})

const subjectOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 44, right: 20, top: 48, bottom: 36 },
  xAxis: { type: 'category', data: data.value.subject_averages.map((item) => item.subject_name) },
  legend: {
    data: [
      { name: '平均分', icon: 'roundRect' },
      { name: '科目满分', icon: 'roundRect' },
    ],
    top: 0,
    left: 'center',
    itemWidth: 18,
    itemHeight: 8,
    itemGap: 24,
  },
  yAxis: {
    type: 'value',
    name: '分',
    min: 0,
    max: Math.max(100, ...data.value.subject_averages.map((item) => item.max_score)),
  },
  series: [
    {
      name: '平均分',
      type: 'bar',
      data: data.value.subject_averages.map((item) => item.average_score),
      barMaxWidth: 34,
      itemStyle: { color: '#2f7bff', borderRadius: [7, 7, 0, 0] },
    },
    {
      name: '科目满分',
      type: 'line',
      symbol: 'circle',
      data: data.value.subject_averages.map((item) => item.max_score),
      lineStyle: { type: 'dashed', width: 2, color: '#9aa6b2' },
      itemStyle: { color: '#9aa6b2' },
    },
  ],
}))

const trendOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 44, right: 20, top: 48, bottom: 36 },
  legend: {
    data: [{ name: '得分率', icon: 'roundRect' }],
    top: 0,
    left: 'center',
    itemWidth: 18,
    itemHeight: 8,
  },
  xAxis: { type: 'category', data: data.value.exam_trend.map((item) => item.exam_name) },
  yAxis: { type: 'value', name: '得分率（%）', min: 0, max: 100 },
  series: [{
    type: 'line', smooth: true, symbolSize: 8,
    name: '得分率',
    data: data.value.exam_trend.map((item) => item.score_rate),
    lineStyle: { width: 3, color: '#11a683' },
    itemStyle: { color: '#11a683' },
    areaStyle: { color: 'rgba(17, 166, 131, .09)' },
  }],
}))

const distributionOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 44, right: 20, top: 24, bottom: 36 },
  xAxis: { type: 'category', data: insights.value.score_distribution.map((item) => item.label) },
  yAxis: { type: 'value', minInterval: 1 },
  series: [{
    type: 'bar',
    data: insights.value.score_distribution.map((item) => item.count),
    barMaxWidth: 42,
    itemStyle: { color: '#7956c7', borderRadius: [7, 7, 0, 0] },
  }],
}))

const gradeComparisonOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 44, right: 20, top: 48, bottom: 36 },
  legend: { data: ['得分率', '及格率'], top: 0, left: 'center' },
  xAxis: { type: 'category', data: data.value.grade_comparison.map((item) => item.grade_level) },
  yAxis: { type: 'value', name: '%', min: 0, max: 100 },
  series: [
    { name: '得分率', type: 'bar', data: data.value.grade_comparison.map((item) => item.score_rate), itemStyle: { color: '#2f7bff', borderRadius: [7, 7, 0, 0] } },
    { name: '及格率', type: 'line', data: data.value.grade_comparison.map((item) => item.pass_rate), itemStyle: { color: '#11a683' }, lineStyle: { width: 3, color: '#11a683' } },
  ],
}))

const yearComparisonOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 44, right: 20, top: 48, bottom: 36 },
  legend: { data: ['得分率', '及格率'], top: 0, left: 'center' },
  xAxis: { type: 'category', data: data.value.year_comparison.map((item) => item.academic_year) },
  yAxis: { type: 'value', name: '%', min: 0, max: 100 },
  series: [
    { name: '得分率', type: 'bar', data: data.value.year_comparison.map((item) => item.score_rate), itemStyle: { color: '#7956c7', borderRadius: [7, 7, 0, 0] } },
    { name: '及格率', type: 'line', data: data.value.year_comparison.map((item) => item.pass_rate), itemStyle: { color: '#11a683' }, lineStyle: { width: 3, color: '#11a683' } },
  ],
}))

const comparableDetailScope = computed(() => !data.value.mixed_grade_scope && !data.value.mixed_academic_year_scope)

const scopeChip = computed(() => {
  const scope = data.value.applied_scope
  return [scope.academic_year && `${scope.academic_year} 学年`, scope.grade_level, scope.cohort_year && `${scope.cohort_year}届`]
    .filter(Boolean).join(' · ') || '当前全部可见范围'
})

const showGradeFilters = computed(() => auth.user?.role === 'academic_admin')
const showClassFilter = computed(() => ['academic_admin', 'subject_teacher'].includes(auth.user?.role || '') || filterOptions.value.classes.length > 1)
const showSubjectFilter = computed(() => ['academic_admin', 'head_teacher'].includes(auth.user?.role || '') || filterOptions.value.subjects.length > 1)
const showExamFilter = computed(() => filterOptions.value.exams.length > 0)

const topAlerts = computed<LearningAlert[]>(() => [
  ...insights.value.current_risks,
  ...insights.value.fluctuations,
  ...insights.value.anomalies,
].sort((left, right) => Number(right.severity === 'high') - Number(left.severity === 'high')).slice(0, 8))

const cards = computed(() => [
  { label: '整体得分率', value: data.value.overall_score_rate.toFixed(1), suffix: '%', icon: ChartBarIcon, tone: 'blue' },
  { label: '及格率', value: data.value.pass_rate.toFixed(1), suffix: '%', icon: CheckCircleIcon, tone: 'green' },
  { label: '学生数', value: data.value.student_count, suffix: '人', icon: UsergroupIcon, tone: 'amber' },
  { label: '考试场次', value: data.value.exam_count, suffix: '次', icon: FileIcon, tone: 'violet' },
])

const taskStatusLabel = computed(() => ({
  queued: '等待执行',
  running: '执行中',
  success: '已完成',
  error: '执行失败',
  cancelled: '已取消',
  interrupted: '已中断',
}[task.value?.status || ''] || task.value?.status || '未启动'))

const taskIsActive = computed(() => ['queued', 'running'].includes(task.value?.status || ''))
const alertPageCount = computed(() => Math.max(1, Math.ceil(alertPage.value.total / alertPage.value.page_size)))
const notificationEnabled = computed(() => notificationState.value === 'enabled')
const notificationButtonLabel = computed(() => ({
  unsupported: '浏览器不支持提醒',
  off: '开启风险提醒',
  denied: '风险提醒被浏览器禁用',
  enabled: '风险提醒：已开启',
}[notificationState.value]))
const notificationDescription = computed(() => ({
  unsupported: '当前浏览器不支持系统通知。',
  off: '开启后，本页面加载或重新计算风险时，如高风险集合发生变化，将发送系统通知。',
  denied: '浏览器已拒绝通知权限，需要在站点设置中重新允许。',
  enabled: '已开启；仅在浏览器会话中检测变化，不会在页面关闭后后台推送。',
}[notificationState.value]))

async function startAgentTask(taskType: AgentTask['task_type']) {
  try {
    const scope: AgentTaskScope = { ...activeScope.value }
    if (taskScope.class_name) scope.class_name = taskScope.class_name
    if (taskScope.subject_name) scope.subject_name = taskScope.subject_name
    if (taskType === 'batch_report' && taskScope.exam_name) scope.exam_name = taskScope.exam_name
    await taskStore.start(taskType, scope)
    MessagePlugin.success('任务已提交，可继续使用其他功能')
  } catch (error: any) {
    MessagePlugin.error(error.response?.data?.detail || '异步任务启动失败')
  }
}

async function refreshAgentTask(silent = false) {
  if (!task.value) return
  try {
    await taskStore.refresh(task.value.task_id)
    if (!silent) MessagePlugin.success('任务状态已更新')
  } catch (error: any) {
    if (!silent) MessagePlugin.error(error.response?.data?.detail || '任务状态查询失败')
  }
}

async function cancelAgentTask() {
  if (!task.value) return
  try {
    await taskStore.cancel(task.value.task_id)
    MessagePlugin.success('任务已取消')
  } catch (error: any) {
    MessagePlugin.error(error.response?.data?.detail || '任务取消失败')
  }
}

async function updateAgentTask() {
  if (!task.value || !taskUpdate.value.trim()) return
  try {
    await taskStore.update(task.value.task_id, taskUpdate.value.trim())
    taskUpdate.value = ''
    MessagePlugin.success('补充要求已提交，当前运行将被新任务替换')
  } catch (error: any) {
    MessagePlugin.error(error.response?.data?.detail || '任务更新失败')
  }
}

async function retryAgentTask() {
  if (!task.value?.can_retry) return
  try {
    await taskStore.retry(task.value.task_id)
    MessagePlugin.success('任务已重新提交')
  } catch (error: any) {
    MessagePlugin.error(error.response?.data?.detail || '任务重新执行失败')
  }
}

function formatTaskTime(value?: string | null) {
  if (!value) return '未知'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

async function generateReport() {
  reportLoading.value = true
  try {
    report.value = (await reportsApi.generate(activeScope.value)).data
    MessagePlugin.success('AI 报告已生成')
  } catch (error: any) {
    MessagePlugin.error(error.response?.data?.detail || '报告生成失败，请稍后重试')
  } finally {
    reportLoading.value = false
  }
}

async function loadDashboard() {
  loading.value = true
  try {
    const [dashboardResponse, insightResponse, riskResponse] = await Promise.all([
      dashboardApi.summary(activeScope.value),
      insightsApi.summary(activeScope.value),
      risksApi.summary(activeScope.value),
    ])
    data.value = dashboardResponse.data
    insights.value = insightResponse.data
    risks.value = riskResponse.data
    notifyRiskChanges()
  } catch (error: any) {
    MessagePlugin.error(error.response?.data?.detail || '看板加载失败')
  } finally {
    loading.value = false
  }
}

function normalizedDraftScope(): AnalysisScope {
  return {
    academic_year: filterDraft.academic_year || undefined,
    grade_level: filterDraft.grade_level || undefined,
    term: filterDraft.term || undefined,
    exam_type: filterDraft.exam_type || undefined,
    cohort_year: filterDraft.cohort_year ? Number(filterDraft.cohort_year) : undefined,
    class_name: filterDraft.class_name || undefined,
    subject_name: filterDraft.subject_name || undefined,
    exam_name: filterDraft.exam_name || undefined,
  }
}

function fillFilterDraft(scope: AnalysisScope) {
  filterDraft.academic_year = scope.academic_year || ''
  filterDraft.grade_level = scope.grade_level || ''
  filterDraft.term = scope.term || ''
  filterDraft.exam_type = scope.exam_type || ''
  filterDraft.cohort_year = scope.cohort_year ? String(scope.cohort_year) : ''
  filterDraft.class_name = scope.class_name || ''
  filterDraft.subject_name = scope.subject_name || ''
  filterDraft.exam_name = scope.exam_name || ''
}

function sanitizeFilterDraft(options: AnalysisFilterOptions): boolean {
  let changed = false
  const clear = (field: FilterField) => {
    if (filterDraft[field]) {
      filterDraft[field] = ''
      changed = true
    }
  }
  if (filterDraft.academic_year && !options.academic_years.includes(filterDraft.academic_year)) clear('academic_year')
  if (filterDraft.grade_level && !options.grade_levels.includes(filterDraft.grade_level)) clear('grade_level')
  if (filterDraft.term && !options.terms.includes(filterDraft.term)) clear('term')
  if (filterDraft.exam_type && !options.exam_types.includes(filterDraft.exam_type)) clear('exam_type')
  if (filterDraft.cohort_year && !options.cohort_years.includes(Number(filterDraft.cohort_year))) clear('cohort_year')
  if (filterDraft.class_name && !options.classes.includes(filterDraft.class_name)) clear('class_name')
  if (filterDraft.subject_name && !options.subjects.includes(filterDraft.subject_name)) clear('subject_name')
  if (filterDraft.exam_name && !options.exams.includes(filterDraft.exam_name)) clear('exam_name')
  return changed
}

async function refreshFilterOptions() {
  const request = ++filterOptionRequest
  filterOptionsLoading.value = true
  try {
    for (let pass = 0; pass < 2; pass += 1) {
      const nextOptions = (await dashboardApi.options(normalizedDraftScope())).data
      if (request !== filterOptionRequest) return
      nextOptions.defaults = defaultScope.value
      filterOptions.value = nextOptions
      if (!sanitizeFilterDraft(nextOptions)) break
    }
  } finally {
    if (request === filterOptionRequest) filterOptionsLoading.value = false
  }
}

async function handleFilterChange(field: FilterField) {
  await nextTick()
  if (field === 'academic_year') {
    filterDraft.grade_level = ''
    filterDraft.cohort_year = ''
    filterDraft.class_name = ''
    filterDraft.subject_name = ''
    filterDraft.exam_name = ''
  } else if (field === 'grade_level') {
    filterDraft.cohort_year = ''
    filterDraft.class_name = ''
    filterDraft.subject_name = ''
    filterDraft.exam_name = ''
  } else if (field === 'cohort_year') {
    filterDraft.grade_level = ''
    filterDraft.class_name = ''
    filterDraft.subject_name = ''
    filterDraft.exam_name = ''
  } else if (field === 'term' || field === 'exam_type' || field === 'class_name') {
    filterDraft.exam_name = ''
  }
  try {
    await refreshFilterOptions()
  } catch (error: any) {
    MessagePlugin.error(error.response?.data?.detail || '筛选选项更新失败')
  }
}

async function loadFilterOptions() {
  const initialOptions = (await dashboardApi.options()).data
  defaultScope.value = initialOptions.defaults
  filterOptions.value = initialOptions
  fillFilterDraft({ ...defaultScope.value, ...loadAnalysisScope(auth.user?.id) })
  sanitizeFilterDraft(initialOptions)
  await refreshFilterOptions()
  activeScope.value = normalizedDraftScope()
  saveAnalysisScope(auth.user?.id, activeScope.value)
  filtersReady.value = true
}

async function applyAnalysisFilters() {
  await refreshFilterOptions()
  activeScope.value = normalizedDraftScope()
  saveAnalysisScope(auth.user?.id, activeScope.value)
  report.value = null
  await loadDashboard()
  MessagePlugin.success('分析范围已更新')
}

async function resetAnalysisFilters() {
  fillFilterDraft(defaultScope.value)
  await applyAnalysisFilters()
}

function notificationKey(suffix: string) {
  return `gradewise:risk-notification:${auth.user?.id || 'anonymous'}:${suffix}`
}

function initializeNotifications() {
  if (!('Notification' in window)) {
    notificationState.value = 'unsupported'
    return
  }
  if (Notification.permission === 'denied') {
    notificationState.value = 'denied'
    return
  }
  notificationState.value = Notification.permission === 'granted'
    && localStorage.getItem(notificationKey('enabled')) === '1'
    ? 'enabled'
    : 'off'
}

function notifyRiskChanges(force = false): boolean {
  if (!notificationEnabled.value || !('Notification' in window) || Notification.permission !== 'granted') return false
  const highRisks = risks.value.predictions.filter((item) => item.risk_level === 'high')
  const fingerprint = highRisks
    .map((item) => `${item.student_id}:${item.subject_id}:${item.risk_score.toFixed(1)}`)
    .sort()
    .join('|')
  const fingerprintKey = notificationKey('fingerprint')
  if (!force && localStorage.getItem(fingerprintKey) === fingerprint) return false
  localStorage.setItem(fingerprintKey, fingerprint)
  if (!highRisks.length) return false
  const examples = highRisks.slice(0, 3).map((item) => `${item.student_name}·${item.subject_name}`).join('、')
  new Notification(`GradeWise：发现 ${highRisks.length} 项高风险`, {
    body: `${examples}${highRisks.length > 3 ? ' 等' : ''}。请进入挂科风险区域查看原因。`,
  })
  return true
}

async function toggleRiskNotifications() {
  if (notificationState.value === 'unsupported') return
  if (notificationEnabled.value) {
    localStorage.removeItem(notificationKey('enabled'))
    notificationState.value = 'off'
    MessagePlugin.success('风险提醒已关闭')
    return
  }
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') {
    notificationState.value = permission === 'denied' ? 'denied' : 'off'
    MessagePlugin.warning('未获得浏览器通知权限')
    return
  }
  localStorage.setItem(notificationKey('enabled'), '1')
  notificationState.value = 'enabled'
  const sent = notifyRiskChanges(true)
  MessagePlugin.success(sent ? '风险提醒已开启，并已发送当前状态通知' : '风险提醒已开启；当前没有高风险记录')
}

async function refreshRiskPredictions() {
  riskRefreshing.value = true
  try {
    risks.value = (await risksApi.refresh(activeScope.value)).data
    notifyRiskChanges()
    MessagePlugin.success('风险已重新计算并保存快照')
  } catch (error: any) {
    MessagePlugin.error(error.response?.data?.detail || '风险重新计算失败')
  } finally {
    riskRefreshing.value = false
  }
}

async function loadAlertPage(type = selectedAlertType.value, page = 1) {
  alertsLoading.value = true
  selectedAlertType.value = type
  try {
    alertPage.value = (await insightsApi.alerts(type, page, 20, activeScope.value)).data
  } catch (error: any) {
    MessagePlugin.error(error.response?.data?.detail || '学情记录加载失败')
  } finally {
    alertsLoading.value = false
  }
}

function openAllAlerts(type: AlertPage['alert_type'] = 'current_risk') {
  alertsOpen.value = true
  loadAlertPage(type, 1)
}

function chooseImportFile() {
  importInput.value?.click()
}

async function importScores(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  importLoading.value = true
  try {
    const { data: result } = await importsApi.scores(file)
    MessagePlugin.success(`导入完成：成功 ${result.accepted_rows} 行，拒绝 ${result.rejected_rows} 行`)
    await loadDashboard()
  } catch (error: any) {
    MessagePlugin.error(error.response?.data?.detail || '成绩导入失败')
  } finally {
    importLoading.value = false
    input.value = ''
  }
}

async function exportChart(
  chartType: 'bar' | 'line',
  title: string,
  option: Record<string, unknown>,
) {
  try {
    const { data: blob } = await chartsApi.exportSvg(chartType, title, option)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${title}.svg`
    anchor.click()
    URL.revokeObjectURL(url)
  } catch (error: any) {
    MessagePlugin.error(error.response?.data?.detail || '图表导出失败')
  }
}

onMounted(async () => {
  initializeNotifications()
  if (auth.user?.role !== 'student') taskStore.initialize(auth.user?.id)
  try {
    await loadFilterOptions()
    await loadDashboard()
  } catch (error: any) {
    loading.value = false
    MessagePlugin.error(error.response?.data?.detail || '分析范围初始化失败')
  }
})
</script>

<template>
  <AppShell>
    <div class="dashboard-page">
      <header class="page-header">
        <div><p class="kicker">OVERVIEW</p><h1>数据看板</h1><p class="muted">{{ data.scope_description || '当前权限范围内的成绩概览' }}</p></div>
        <div class="header-actions">
          <t-button :theme="notificationEnabled ? 'success' : 'warning'" variant="outline" :disabled="notificationState === 'unsupported'" @click="toggleRiskNotifications">{{ notificationButtonLabel }}</t-button>
          <t-button v-if="auth.user?.role === 'academic_admin'" :loading="importLoading" variant="outline" @click="chooseImportFile">导入成绩</t-button>
          <input ref="importInput" hidden type="file" accept=".csv,.xlsx,.json" @change="importScores" />
          <div class="date-chip">{{ scopeChip }}</div>
        </div>
      </header>
      <section v-if="filtersReady" class="analysis-filter-bar">
        <div class="analysis-filter-copy"><strong>分析范围</strong><small>筛选项只包含当前账号有权查看的数据</small></div>
        <div class="analysis-filter-fields">
          <label><span>学年</span><select v-model="filterDraft.academic_year" :disabled="filterOptionsLoading" @change="handleFilterChange('academic_year')"><option value="">全部学年</option><option v-for="item in filterOptions.academic_years" :key="item" :value="item">{{ item }}</option></select></label>
          <label v-if="showGradeFilters"><span>年级</span><select v-model="filterDraft.grade_level" :disabled="filterOptionsLoading" @change="handleFilterChange('grade_level')"><option value="">全部年级</option><option v-for="item in filterOptions.grade_levels" :key="item" :value="item">{{ item }}</option></select></label>
          <label v-if="showGradeFilters"><span>届别</span><select v-model="filterDraft.cohort_year" :disabled="filterOptionsLoading" @change="handleFilterChange('cohort_year')"><option value="">全部届别</option><option v-for="item in filterOptions.cohort_years" :key="item" :value="String(item)">{{ item }}届</option></select></label>
          <label><span>学期</span><select v-model="filterDraft.term" :disabled="filterOptionsLoading" @change="handleFilterChange('term')"><option value="">全部学期</option><option v-for="item in filterOptions.terms" :key="item" :value="item">{{ item }}</option></select></label>
          <label><span>考试类型</span><select v-model="filterDraft.exam_type" :disabled="filterOptionsLoading" @change="handleFilterChange('exam_type')"><option value="">全部类型</option><option v-for="item in filterOptions.exam_types" :key="item" :value="item">{{ item }}</option></select></label>
          <label v-if="showClassFilter"><span>班级</span><select v-model="filterDraft.class_name" :disabled="filterOptionsLoading" @change="handleFilterChange('class_name')"><option value="">全部可见班级</option><option v-for="item in filterOptions.classes" :key="item" :value="item">{{ item }}</option></select></label>
          <label v-if="showSubjectFilter"><span>科目</span><select v-model="filterDraft.subject_name" :disabled="filterOptionsLoading" @change="handleFilterChange('subject_name')"><option value="">全部可见科目</option><option v-for="item in filterOptions.subjects" :key="item" :value="item">{{ item }}</option></select></label>
          <label v-if="showExamFilter"><span>具体考试</span><select v-model="filterDraft.exam_name" :disabled="filterOptionsLoading" @change="handleFilterChange('exam_name')"><option value="">全部考试</option><option v-for="item in filterOptions.exams" :key="item" :value="item">{{ item }}</option></select></label>
        </div>
        <div class="analysis-filter-actions"><t-button size="small" variant="outline" :disabled="filterOptionsLoading" @click="resetAnalysisFilters">恢复默认</t-button><t-button size="small" :loading="loading || filterOptionsLoading" @click="applyAnalysisFilters">应用筛选</t-button></div>
      </section>
      <div v-if="loading" class="dashboard-loading"><t-loading text="正在汇总数据" /></div>
      <template v-else>
        <p class="comparison-note" :class="{ warning: !comparableDetailScope }">{{ data.comparison_note }}</p>
        <section class="metric-grid">
          <article v-for="card in cards" :key="card.label" class="metric-card">
            <div class="metric-icon" :class="card.tone"><component :is="card.icon" /></div>
            <div><p>{{ card.label }}</p><strong>{{ card.value }}<small>{{ card.suffix }}</small></strong></div>
          </article>
        </section>
        <section class="chart-grid">
          <article v-if="data.mixed_academic_year_scope" class="panel"><header><h2>各学年得分率与及格率</h2><button class="chart-export" @click="exportChart('bar', '各学年得分率与及格率', yearComparisonOption)">导出 SVG</button></header><EChart :option="yearComparisonOption" /></article>
          <article v-else-if="data.mixed_grade_scope" class="panel"><header><h2>各年级得分率与及格率</h2><button class="chart-export" @click="exportChart('bar', '各年级得分率与及格率', gradeComparisonOption)">导出 SVG</button></header><EChart :option="gradeComparisonOption" /></article>
          <article v-if="comparableDetailScope" class="panel"><header><h2>各科平均分</h2><button class="chart-export" @click="exportChart('bar', '各科平均分', subjectOption)">导出 SVG</button></header><EChart :option="subjectOption" /></article>
          <article v-if="comparableDetailScope" class="panel"><header><h2>考试得分率趋势</h2><button class="chart-export" @click="exportChart('line', '考试得分率趋势', trendOption)">导出 SVG</button></header><EChart :option="trendOption" /></article>
          <article v-if="comparableDetailScope" class="panel"><header><div><h2>最近考试学生得分率分布</h2><small>{{ insights.distribution_exam_name }} · {{ insights.distribution_sample_size }} 人</small></div><button class="chart-export" @click="exportChart('bar', '最近考试学生得分率分布', distributionOption)">导出 SVG</button></header><EChart :option="distributionOption" /></article>
          <article class="panel alert-panel">
            <header><h2>学情关注</h2><div class="alert-header-actions"><span>共 {{ insights.alert_count }} 条</span><button class="chart-export" @click="openAllAlerts()">查看全部</button></div></header>
            <div v-if="topAlerts.length" class="alert-list">
              <div v-for="alert in topAlerts" :key="`${alert.type}-${alert.student_id}-${alert.exam_name}-${alert.subject_name}`" class="alert-item">
                <span class="severity-dot" :class="alert.severity" />
                <div>
                  <strong>{{ alert.student_name }} · {{ alert.subject_name }}</strong>
                  <p>{{ alert.title }}：{{ alert.detail }}</p>
                  <small>{{ alert.class_name }} · {{ alert.exam_name }}</small>
                </div>
              </div>
            </div>
            <div v-else class="empty-insight">当前范围暂无异常、显著波动或最新不及格记录</div>
          </article>
        </section>
        <section class="risk-panel">
          <header>
            <div><p class="kicker">PREDICTIVE RISK</p><h2>挂科风险估计</h2></div>
            <div class="risk-header-actions"><div class="risk-counts"><span class="high">高风险 {{ risks.high_count }}</span><span>中风险 {{ risks.medium_count }}</span></div><t-button v-if="auth.user?.role === 'academic_admin'" size="small" variant="outline" :loading="riskRefreshing" @click="refreshRiskPredictions">重新计算</t-button></div>
          </header>
          <p class="risk-disclaimer">{{ risks.disclaimer }}</p>
          <p class="notification-hint" :class="notificationState"><strong>{{ notificationButtonLabel }}</strong> {{ notificationDescription }}</p>
          <div v-if="risks.predictions.some((item) => item.risk_level !== 'low')" class="risk-grid">
            <article v-for="item in risks.predictions.filter((risk) => risk.risk_level !== 'low').slice(0, 8)" :key="`${item.student_id}-${item.subject_id}`" class="risk-card" :class="item.risk_level">
              <div><strong>{{ item.student_name }} · {{ item.subject_name }}</strong><span>{{ item.risk_score.toFixed(1) }}</span></div>
              <p>{{ item.reasons.join('；') }}</p>
              <small>最近 {{ item.latest_score.toFixed(1) }} 分 · 趋势 {{ item.trend > 0 ? '+' : '' }}{{ item.trend.toFixed(1) }} 分</small>
            </article>
          </div>
          <div v-else class="empty-report">当前权限范围未发现中高风险记录</div>
        </section>
        <section v-if="auth.user?.role !== 'student'" class="task-panel">
          <header>
            <div><p class="kicker">AGENT PROTOCOL</p><h2>异步智能体任务</h2></div>
            <span v-if="task" class="task-status" :class="task.status">{{ taskStatusLabel }}</span>
          </header>
          <p class="task-description">批量报告和全校预警由独立 Agent Protocol 服务执行。提交后可切换到智能问数，任务会继续运行并在全局显示状态。</p>
          <p v-if="task" class="task-stage-message">{{ task.status_message }}</p>
          <div class="task-scope-grid">
            <label><span>班级范围</span><select v-model="taskScope.class_name"><option value="">全部可见班级</option><option v-for="item in taskOptions.classes" :key="item" :value="item">{{ item }}</option></select></label>
            <label><span>科目范围</span><select v-model="taskScope.subject_name"><option value="">全部可见科目</option><option v-for="item in taskOptions.subjects" :key="item" :value="item">{{ item }}</option></select></label>
            <label><span>考试范围（仅报告）</span><select v-model="taskScope.exam_name"><option value="">全部可见考试</option><option v-for="item in taskOptions.exams" :key="item" :value="item">{{ item }}</option></select></label>
          </div>
          <div class="task-actions">
            <t-button :loading="taskLoading" :disabled="taskIsActive" @click="startAgentTask('batch_report')">启动批量报告</t-button>
            <t-button v-if="auth.user?.role === 'academic_admin'" theme="warning" :loading="taskLoading" :disabled="taskIsActive" @click="startAgentTask('batch_warning')">启动批量预警</t-button>
            <t-button v-if="task" variant="outline" :disabled="taskLoading" @click="refreshAgentTask(false)">查询状态</t-button>
            <t-button v-if="taskIsActive" theme="danger" variant="outline" :loading="taskLoading" @click="cancelAgentTask">取消任务</t-button>
            <t-button v-if="task?.can_retry" class="task-retry" theme="warning" :loading="taskLoading" @click="retryAgentTask">重新执行</t-button>
          </div>
          <div v-if="tasks.length" class="task-history-select">
            <label>历史任务</label>
            <select :value="currentTaskId" @change="taskStore.select(($event.target as HTMLSelectElement).value)">
              <option v-for="item in tasks" :key="item.task_id" :value="item.task_id">{{ item.task_type === 'batch_report' ? '批量报告' : '批量预警' }} · {{ item.scope.class_name || '全部班级' }} · {{ item.scope.subject_name || '全部科目' }} · {{ item.status }}</option>
            </select>
          </div>
          <div v-if="taskIsActive" class="task-update">
            <t-input v-model="taskUpdate" maxlength="3000" placeholder="补充要求，例如：按班级分组并突出高风险原因" @enter="updateAgentTask" />
            <t-button variant="outline" :disabled="!taskUpdate.trim()" :loading="taskLoading" @click="updateAgentTask">更新任务</t-button>
          </div>
          <div v-if="task" class="task-meta">
            <small>任务 ID：{{ task.task_id }} · 范围：{{ task.scope.class_name || '全部班级' }} / {{ task.scope.subject_name || '全部科目' }} / {{ task.scope.exam_name || '全部考试' }}</small>
            <small>尝试次数：{{ task.attempt_count }} · 最近更新：{{ formatTaskTime(task.updated_at) }}</small>
            <p v-if="task.error_code" class="task-error">任务未完成；服务恢复后可使用“重新执行”再次生成。</p>
            <TaskResult v-if="task.result" :content="task.result" />
          </div>
        </section>
        <section class="report-panel">
          <header>
            <div><p class="kicker">AI REPORT</p><h2>{{ report?.title || '个性化学情报告' }}</h2></div>
            <t-button theme="primary" :loading="reportLoading" @click="generateReport">{{ report ? '重新生成' : '生成报告' }}</t-button>
          </header>
          <div v-if="report" class="report-content">
            <p class="report-overview">{{ report.overview }}</p>
            <p class="warning-summary">{{ report.warning_summary }}</p>
            <div class="report-columns">
              <div><h3>表现亮点</h3><ul><li v-for="item in report.highlights" :key="item">{{ item }}</li></ul></div>
              <div><h3>关注事项</h3><ul><li v-for="item in report.concerns" :key="item">{{ item }}</li><li v-if="!report.concerns.length">暂无显著风险</li></ul></div>
              <div><h3>建议行动</h3><ul><li v-for="item in report.recommendations" :key="item">{{ item }}</li></ul></div>
            </div>
            <blockquote>{{ report.ai_comment }}</blockquote>
            <small>由 {{ report.generated_by === 'qwen' ? '通义千问' : report.generated_by === 'deepseek' ? 'DeepSeek' : '规则模板' }} 基于脱敏统计生成</small>
          </div>
          <p v-else class="empty-report">基于当前账号可见范围的确定性统计和预警证据生成；姓名不会发送给大模型。</p>
        </section>
      </template>
    </div>
    <div v-if="alertsOpen" class="modal-backdrop" @click.self="alertsOpen = false">
      <section class="alerts-modal" role="dialog" aria-modal="true" aria-label="全部学情关注记录">
        <header><div><p class="kicker">ALL ALERTS</p><h2>全部学情关注记录</h2><small>{{ data.scope_description }}</small></div><button class="modal-close" aria-label="关闭" @click="alertsOpen = false">×</button></header>
        <nav class="alert-tabs">
          <button :class="{ active: selectedAlertType === 'current_risk' }" @click="loadAlertPage('current_risk', 1)">最新未及格 {{ insights.alert_counts.current_risk }}</button>
          <button :class="{ active: selectedAlertType === 'fluctuation' }" @click="loadAlertPage('fluctuation', 1)">成绩波动 {{ insights.alert_counts.fluctuation }}</button>
          <button :class="{ active: selectedAlertType === 'anomaly' }" @click="loadAlertPage('anomaly', 1)">同组异常 {{ insights.alert_counts.anomaly }}</button>
        </nav>
        <div class="modal-alert-list" :class="{ loading: alertsLoading }">
          <div v-if="alertsLoading" class="modal-loading"><t-loading text="正在加载记录" /></div>
          <div v-else-if="alertPage.items.length" v-for="alert in alertPage.items" :key="`${alert.type}-${alert.student_id}-${alert.exam_name}-${alert.subject_name}`" class="alert-item">
            <span class="severity-dot" :class="alert.severity" />
            <div><strong>{{ alert.student_name }} · {{ alert.subject_name }}</strong><p>{{ alert.title }}：{{ alert.detail }}</p><small>{{ alert.class_name }} · {{ alert.exam_name }}</small></div>
          </div>
          <div v-else class="empty-insight">当前类型暂无记录</div>
        </div>
        <footer><span>第 {{ alertPage.page }} / {{ alertPageCount }} 页，共 {{ alertPage.total }} 条</span><div><t-button size="small" variant="outline" :disabled="alertPage.page <= 1 || alertsLoading" @click="loadAlertPage(selectedAlertType, alertPage.page - 1)">上一页</t-button><t-button size="small" variant="outline" :disabled="alertPage.page >= alertPageCount || alertsLoading" @click="loadAlertPage(selectedAlertType, alertPage.page + 1)">下一页</t-button></div></footer>
      </section>
    </div>
  </AppShell>
</template>
