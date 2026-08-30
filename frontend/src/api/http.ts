import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import type { TokenResponse } from '@/types'

const baseURL = import.meta.env.VITE_API_BASE_URL || '/api'

export const http = axios.create({ baseURL, timeout: 45_000 })

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem('gradewise.access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

let refreshing: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  const refreshToken = localStorage.getItem('gradewise.refresh_token')
  if (!refreshToken) throw new Error('No refresh token')
  const { data } = await axios.post<TokenResponse>(`${baseURL}/auth/refresh`, {
    refresh_token: refreshToken,
  })
  localStorage.setItem('gradewise.access_token', data.access_token)
  localStorage.setItem('gradewise.refresh_token', data.refresh_token)
  localStorage.setItem('gradewise.user', JSON.stringify(data.user))
  return data.access_token
}

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const request = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined
    if (error.response?.status === 401 && request && !request._retried && !request.url?.includes('/auth/')) {
      request._retried = true
      try {
        refreshing ??= refreshAccessToken().finally(() => {
          refreshing = null
        })
        const token = await refreshing
        request.headers.Authorization = `Bearer ${token}`
        return http(request)
      } catch {
        localStorage.removeItem('gradewise.access_token')
        localStorage.removeItem('gradewise.refresh_token')
        localStorage.removeItem('gradewise.user')
        if (window.location.pathname !== '/login') window.location.assign('/login')
      }
    }
    return Promise.reject(error)
  },
)

