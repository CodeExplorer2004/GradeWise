import { expect, test } from '@playwright/test'

const interruptedTask = {
  task_id: 'task-1',
  run_id: 'missing-run',
  task_type: 'batch_report',
  status: 'interrupted',
  stage: 'interrupted',
  status_message: 'Agent 运行环境已重启，可重新执行',
  result: null,
  scope: { class_name: '初一（1）班', subject_name: '数学' },
  requested_scope: { class_name: '初一（1）班' },
  error_code: 'worker_state_missing',
  attempt_count: 1,
  can_retry: true,
  created_at: '2026-09-10T10:00:00Z',
  updated_at: '2026-09-10T10:05:00Z',
}

test('中断的 Agent 任务显示原因、尝试次数并可重新执行', async ({ page }) => {
  let releaseRiskSummary = () => {}
  let signalRiskSummaryRequest = () => {}
  const riskSummaryGate = new Promise<void>((resolve) => {
    releaseRiskSummary = resolve
  })
  const riskSummaryRequested = new Promise<void>((resolve) => {
    signalRiskSummaryRequest = resolve
  })

  await page.route('**/api/risks/summary**', async (route) => {
    signalRiskSummaryRequest()
    await riskSummaryGate
    await route.continue()
  })
  await page.route('**/api/tasks', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: [interruptedTask] })
      return
    }
    await route.continue()
  })
  await page.route('**/api/tasks/options', async (route) => {
    await route.fulfill({ json: { classes: [], subjects: [], exams: [] } })
  })
  await page.route('**/api/tasks/task-1/retry', async (route) => {
    await route.fulfill({
      json: {
        ...interruptedTask,
        run_id: 'run-2',
        status: 'running',
        stage: 'agent_running',
        status_message: 'Agent 正在生成报告',
        error_code: null,
        attempt_count: 2,
        can_retry: false,
        updated_at: '2026-09-10T10:06:00Z',
      },
    })
  })

  try {
    await page.goto('/login')
    await page.getByPlaceholder('请输入账号').fill('academic01')
    await page.getByPlaceholder('请输入密码').fill('GradeWise123!')
    await page.getByRole('button', { name: '进入系统' }).click()
    await expect(page).toHaveURL(/\/chat$/)

    await page.getByRole('button', { name: /数据看板/ }).click()
    await expect(page).toHaveURL(/\/dashboard$/)
    await riskSummaryRequested
    await expect(page.getByText('Agent 运行环境已重启，可重新执行')).toBeVisible({ timeout: 3000 })
    await expect(page.getByText('尝试次数：1')).toBeVisible()

    await page.getByRole('button', { name: '重新执行' }).click()

    await expect(page.getByText('Agent 正在生成报告')).toBeVisible()
    await expect(page.getByText('尝试次数：2')).toBeVisible()
  } finally {
    releaseRiskSummary()
  }
})
