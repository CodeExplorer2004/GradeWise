<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { LockOnIcon, UserIcon } from 'tdesign-icons-vue-next'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const loading = ref(false)
const form = reactive({ username: 'academic01', password: 'GradeWise123!' })
const accounts = [
  ['academic01', '教务管理员'],
  ['headteacher01', '初三班主任'],
  ['teacher01', '初三教师'],
  ['student01', '初三学生'],
  ['g2_headteacher01', '初二班主任'],
  ['g2_teacher01', '初二教师'],
  ['g2_student01', '初二学生'],
  ['g1_headteacher01', '初一班主任'],
  ['g1_teacher01', '初一教师'],
  ['g1_student01', '初一学生'],
]

async function submit() {
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    await router.replace(String(route.query.redirect || '/chat'))
  } catch (error: any) {
    MessagePlugin.error(error.response?.data?.detail || '登录失败，请检查服务状态')
  } finally {
    loading.value = false
  }
}

function selectAccount(username: string) {
  form.username = username
  form.password = 'GradeWise123!'
}
</script>

<template>
  <div class="login-page">
    <section class="login-story">
      <div class="story-inner">
        <div class="story-eyebrow">ACADEMIC INTELLIGENCE</div>
        <h1>让每一次成绩变化<br />都有迹可循</h1>
        <p>用可信的自然语言查询和清晰的数据图表，帮助教师更早看见趋势，帮助学生更好理解成长。</p>
        <div class="story-metric">
          <strong>4</strong><span>级权限隔离</span><i></i><strong>100%</strong><span>只读问数</span>
        </div>
      </div>
    </section>
    <section class="login-panel">
      <div class="login-card">
        <div class="mobile-brand"><span>G</span> GradeWise</div>
        <p class="kicker">欢迎回来</p>
        <h2>登录 GradeWise</h2>
        <p class="muted">进入你的学情智能工作台</p>
        <t-form :data="form" label-align="top" @submit="submit">
          <t-form-item label="账号" name="username">
            <t-input v-model="form.username" size="large" placeholder="请输入账号">
              <template #prefix-icon><UserIcon /></template>
            </t-input>
          </t-form-item>
          <t-form-item label="密码" name="password">
            <t-input v-model="form.password" type="password" size="large" placeholder="请输入密码">
              <template #prefix-icon><LockOnIcon /></template>
            </t-input>
          </t-form-item>
          <t-button theme="primary" size="large" block type="submit" :loading="loading">进入系统</t-button>
        </t-form>
        <div class="demo-accounts">
          <span>演示账号</span>
          <button v-for="item in accounts" :key="item[0]" @click="selectAccount(item[0])">
            {{ item[1] }}
          </button>
        </div>
      </div>
    </section>
  </div>
</template>
