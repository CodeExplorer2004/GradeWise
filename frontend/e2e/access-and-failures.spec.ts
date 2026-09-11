import { expect, test, type APIRequestContext } from '@playwright/test'

const demoPassword = 'GradeWise123!'

async function login(request: APIRequestContext, username: string) {
  const response = await request.post('/api/auth/login', {
    data: { username, password: demoPassword },
  })
  expect(response.ok(), `${username} 登录失败`).toBeTruthy()
  return response.json()
}

function bearer(accessToken: string) {
  return { Authorization: `Bearer ${accessToken}` }
}

test('四种角色登录后只能看到各自的数据范围', async ({ request }) => {
  const cases = [
    {
      username: 'student01',
      role: 'student',
      studentCount: 1,
      scope: '权限范围：仅本人全部科目',
    },
    {
      username: 'teacher01',
      role: 'subject_teacher',
      studentCount: 84,
      scope: '权限范围：初三1班·语文、初三2班·语文',
    },
    {
      username: 'headteacher01',
      role: 'head_teacher',
      studentCount: 42,
      scope: '权限范围：初三1班·全部科目',
    },
    {
      username: 'academic01',
      role: 'academic_admin',
      studentCount: 756,
      scope: '权限范围：当前学校全部班级、全部科目',
    },
  ] as const

  for (const item of cases) {
    await test.step(item.username, async () => {
      const session = await login(request, item.username)
      expect(session.user.role).toBe(item.role)

      const summaryResponse = await request.get('/api/dashboard/summary', {
        headers: bearer(session.access_token),
      })
      expect(summaryResponse.ok(), `${item.username} 看板加载失败`).toBeTruthy()

      const summary = await summaryResponse.json()
      expect(summary.student_count).toBe(item.studentCount)
      expect(summary.scope_description).toBe(item.scope)
    })
  }
})

test('任课教师请求未授权班级时被服务端拒绝', async ({ request }) => {
  const session = await login(request, 'teacher01')
  const response = await request.get(
    `/api/dashboard/summary?class_name=${encodeURIComponent('初三3班')}`,
    {
      headers: bearer(session.access_token),
    },
  )

  expect(response.status()).toBe(403)
  await expect(response.json()).resolves.toEqual({
    detail: '所选class_name不在当前账号权限范围内',
  })
})

test('同一账号第五次登录失败触发限流', async ({ request }) => {
  const username = `e2e-missing-${Date.now()}`

  for (let attempt = 1; attempt <= 4; attempt += 1) {
    const response = await request.post('/api/auth/login', {
      data: { username, password: 'wrong-password' },
    })
    expect(response.status(), `第 ${attempt} 次失败应返回 401`).toBe(401)
    await expect(response.json()).resolves.toEqual({ detail: '用户名或密码错误' })
  }

  const limited = await request.post('/api/auth/login', {
    data: { username, password: 'wrong-password' },
  })
  expect(limited.status()).toBe(429)
  expect(Number(limited.headers()['retry-after'])).toBeGreaterThan(0)
  await expect(limited.json()).resolves.toEqual({ detail: '登录尝试过于频繁，请稍后再试' })
})

test('教务导入缺少必填字段的文件时返回校验失败', async ({ request }) => {
  const session = await login(request, 'academic01')
  const response = await request.post('/api/imports/scores', {
    headers: bearer(session.access_token),
    multipart: {
      file: {
        name: 'invalid-scores.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from('student_no,score\n20260101,80'),
      },
    },
  })

  expect(response.status()).toBe(200)
  const result = await response.json()
  expect(result).toMatchObject({
    total_rows: 1,
    accepted_rows: 0,
    rejected_rows: 1,
    inserted_rows: 0,
    updated_rows: 0,
  })
  expect(result.errors).toEqual([
    { row: 2, reason: '缺少学号、考试、科目或成绩' },
  ])
})
