import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { Button, Form, FormItem, Input, Loading } from 'tdesign-vue-next'
import 'tdesign-vue-next/es/style/index.css'
import App from './App.vue'
import router from './router'
import './styles/global.css'

const app = createApp(App)
app.component('TButton', Button)
app.component('TForm', Form)
app.component('TFormItem', FormItem)
app.component('TInput', Input)
app.component('TLoading', Loading)
app.use(createPinia()).use(router).mount('#app')
