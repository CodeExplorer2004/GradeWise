import { expect, test } from '@playwright/test'

test('教务登录后可完成问数并看到图表', async ({ page }) => {
  await page.goto('/login')

  await page.getByPlaceholder('请输入账号').fill('academic01')
  await page.getByPlaceholder('请输入密码').fill('GradeWise123!')
  await page.getByRole('button', { name: '进入系统' }).click()

  await expect(page).toHaveURL(/\/chat$/)
  await expect(page.getByRole('heading', { name: '智能问数' })).toBeVisible()

  const queryResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/chat/query') && response.request().method() === 'POST',
  )
  await page.getByPlaceholder('询问成绩、趋势或对比分析…').fill('各科平均分')
  await page.getByRole('button', { name: '发送' }).click()

  const response = await queryResponse
  expect(response.ok()).toBeTruthy()
  const payload = await response.json()
  expect(payload.rows.length).toBeGreaterThan(0)
  expect(payload.chart.type).not.toBe('none')

  await expect(page.getByText(/已返回 \d+ 条数据/)).toBeVisible()
  await expect(page.locator('.inline-chart canvas')).toBeVisible()
  await expect(page.locator('.result-table tbody tr').first()).toBeVisible()
})
