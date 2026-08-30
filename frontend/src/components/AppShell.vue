<script setup lang="ts">
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { ChartAnalyticsIcon, ChatIcon, LogoutIcon } from 'tdesign-icons-vue-next'
import { useAuthStore } from '@/stores/auth'
import { useTaskStore } from '@/stores/tasks'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const taskStore = useTaskStore()
const { activeCount, unreadCompleted } = storeToRefs(taskStore)

const roleNames: Record<string, string> = {
  student: '学生',
  subject_teacher: '任课教师',
  head_teacher: '班主任',
  academic_admin: '教务管理员',
}

function logout() {
  taskStore.reset()
  auth.logout()
  router.replace('/login')
}

onMounted(() => {
  if (auth.user?.role !== 'student') taskStore.initialize(auth.user?.id)
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">G</span>
        <div><strong>GradeWise</strong><small>学情智能分析</small></div>
      </div>
      <nav>
        <button :class="{ active: route.name === 'chat' }" @click="router.push('/chat')">
          <ChatIcon /> 智能问数
        </button>
        <button :class="{ active: route.name === 'dashboard' }" @click="router.push('/dashboard')">
          <ChartAnalyticsIcon /> 数据看板
          <span v-if="activeCount || unreadCompleted" class="nav-task-badge">{{ activeCount || unreadCompleted }}</span>
        </button>
      </nav>
      <button v-if="activeCount" class="global-task-state" @click="router.push('/dashboard')">
        <i></i><span>{{ activeCount }} 个任务后台执行中</span>
      </button>
      <button v-else-if="unreadCompleted" class="global-task-state completed" @click="router.push('/dashboard')">
        <i></i><span>{{ unreadCompleted }} 个任务已完成</span>
      </button>
      <div class="profile">
        <div class="avatar">{{ auth.user?.display_name?.slice(-1) || 'G' }}</div>
        <div class="profile-copy">
          <strong>{{ auth.user?.display_name }}</strong>
          <small>{{ roleNames[auth.user?.role || ''] }}</small>
        </div>
        <t-button theme="default" variant="text" shape="square" aria-label="退出登录" @click="logout">
          <LogoutIcon />
        </t-button>
      </div>
    </aside>
    <main class="shell-main"><slot /></main>
  </div>
</template>
