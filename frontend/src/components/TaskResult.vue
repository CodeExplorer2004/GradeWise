<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ content: string }>()

type Block =
  | { type: 'heading' | 'paragraph' | 'bullet'; text: string }
  | { type: 'divider' }
  | { type: 'table'; headers: string[]; rows: string[][] }

function clean(text: string) {
  return text
    .replace(/\\$/g, '')
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .trim()
}

function cells(line: string) {
  return line.split('|').slice(1, -1).map((item) => clean(item))
}

const blocks = computed<Block[]>(() => {
  const lines = props.content.replace(/\\\r?\n/g, '\n').split(/\r?\n/)
  const result: Block[] = []
  for (let index = 0; index < lines.length;) {
    const line = lines[index].trim()
    if (!line) {
      index += 1
      continue
    }
    if (/^---+$/.test(line)) {
      result.push({ type: 'divider' })
      index += 1
      continue
    }
    if (line.startsWith('|') && line.endsWith('|')) {
      const tableLines: string[] = []
      while (index < lines.length && lines[index].trim().startsWith('|')) {
        tableLines.push(lines[index].trim())
        index += 1
      }
      const contentLines = tableLines.filter((item) => !/^\|[\s:|-]+\|$/.test(item))
      if (contentLines.length) {
        result.push({
          type: 'table',
          headers: cells(contentLines[0]),
          rows: contentLines.slice(1).map(cells),
        })
      }
      continue
    }
    const heading = line.match(/^#{1,6}\s+(.+)$/)
    if (heading || /^\*\*.+\*\*$/.test(line)) {
      result.push({ type: 'heading', text: clean(heading?.[1] || line) })
    } else if (/^(?:[-*]|\d+\.)\s+/.test(line)) {
      result.push({ type: 'bullet', text: clean(line.replace(/^(?:[-*]|\d+\.)\s+/, '')) })
    } else if (line !== '>') {
      result.push({ type: 'paragraph', text: clean(line.replace(/^>\s*/, '')) })
    }
    index += 1
  }
  return result
})
</script>

<template>
  <article class="structured-task-result">
    <template v-for="(block, index) in blocks" :key="index">
      <h3 v-if="block.type === 'heading'">{{ block.text }}</h3>
      <p v-else-if="block.type === 'paragraph'">{{ block.text }}</p>
      <div v-else-if="block.type === 'bullet'" class="task-result-bullet"><i></i><span>{{ block.text }}</span></div>
      <hr v-else-if="block.type === 'divider'" />
      <div v-else-if="block.type === 'table'" class="task-result-table-wrap">
        <table><thead><tr><th v-for="header in block.headers" :key="header">{{ header }}</th></tr></thead>
          <tbody><tr v-for="(row, rowIndex) in block.rows" :key="rowIndex"><td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</td></tr></tbody>
        </table>
      </div>
    </template>
  </article>
</template>
