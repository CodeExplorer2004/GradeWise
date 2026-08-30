import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { authApi } from '@/api'
import type { UserInfo } from '@/types'

const storedUser = localStorage.getItem('gradewise.user')

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserInfo | null>(storedUser ? JSON.parse(storedUser) : null)
  const isAuthenticated = computed(() => Boolean(localStorage.getItem('gradewise.access_token')))

  async function login(username: string, password: string) {
    const { data } = await authApi.login(username, password)
    localStorage.setItem('gradewise.access_token', data.access_token)
    localStorage.setItem('gradewise.refresh_token', data.refresh_token)
    localStorage.setItem('gradewise.user', JSON.stringify(data.user))
    user.value = data.user
  }

  function logout() {
    localStorage.removeItem('gradewise.access_token')
    localStorage.removeItem('gradewise.refresh_token')
    localStorage.removeItem('gradewise.user')
    user.value = null
  }

  return { user, isAuthenticated, login, logout }
})

