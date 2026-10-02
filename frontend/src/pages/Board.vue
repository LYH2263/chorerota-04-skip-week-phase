<template>
  <div>
    <h1 class="brand">本周看板</h1>
    <p class="muted">周卡片网格 · round-robin 落位后可去「对调」申请交换</p>
    <div class="week-tabs">
      <button
        v-for="w in weeks" :key="w.id"
        class="ghost week-tab" :class="{ on: w.id === weekId }"
        @click="pick(w.id)"
      >
        {{ w.label }} <span class="chip" :class="w.status">{{ statusText(w.status) }}</span>
      </button>
      <button class="ghost" @click="addWeek">＋新增周</button>
    </div>
    <div style="display:flex;gap:8px;margin:12px 0">
      <template v-if="week && week.status === 'skipped'">
        <button @click="unskip">取消跳过</button>
      </template>
      <template v-else>
        <button @click="generate">生成周表</button>
        <button class="ghost" @click="skip">跳过本周</button>
      </template>
      <button class="ghost" @click="load">刷新</button>
    </div>
    <p v-if="err" class="err">{{ err }}</p>
    <p v-if="week && week.status === 'skipped'" class="skip-banner">
      本周已整周跳过 · 不生成格子，相位照常前进；取消跳过后可从记录相位重新生成
    </p>
    <div class="week-grid">
      <article v-for="d in days" :key="d" class="week-card" :class="{ skipped: isSkipped }">
        <header>Day {{ d }}</header>
        <template v-if="isSkipped">
          <span class="chip skipped">已跳过</span>
        </template>
        <template v-else>
          <div v-for="a in byDay(d)" :key="a.id">
            <span class="chip">{{ a.task_title }}</span>
            <span class="chip coral">{{ a.member_name }}</span>
          </div>
          <p v-if="!byDay(d).length" class="muted">空</p>
        </template>
      </article>
    </div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
const assigns = ref([])
const weeks = ref([])
const week = ref(null)
const weekId = ref(1)
const days = [0,1,2,3,4,5,6]
const err = ref('')
const isSkipped = computed(() => week.value && week.value.status === 'skipped')
function byDay(d) { return assigns.value.filter(a => a.day === d) }
function statusText(s) { return { draft: '草稿', ready: '已生成', skipped: '已跳过' }[s] || s }
function pick(id) { weekId.value = id; load() }
async function load() {
  err.value = ''
  try {
    // 周列表与看板同源刷新，状态同钉
    weeks.value = await api('/weeks')
    if (!weeks.value.some(w => w.id === weekId.value)) weekId.value = weeks.value[0]?.id || 1
    const b = await api('/weeks/' + weekId.value + '/board')
    week.value = b.week
    assigns.value = b.assignments || []
  } catch (e) { err.value = e.message }
}
async function generate() {
  err.value = ''
  try { await api('/weeks/' + weekId.value + '/generate', { method: 'POST', body: '{}' }); await load() }
  catch (e) { err.value = e.message }
}
async function skip() {
  err.value = ''
  // 与后端一致的取舍：带格周标记跳过即清空格子并作废其 pending 对调
  try { await api('/weeks/' + weekId.value + '/skip', { method: 'POST', body: '{}' }); await load() }
  catch (e) { err.value = e.message }
}
async function unskip() {
  err.value = ''
  try { await api('/weeks/' + weekId.value + '/unskip', { method: 'POST', body: '{}' }); await load() }
  catch (e) { err.value = e.message }
}
async function addWeek() {
  err.value = ''
  const label = prompt('周标签', '第' + (weeks.value.length + 1) + '周')
  if (label === null) return
  try {
    const w = await api('/weeks', { method: 'POST', body: JSON.stringify({ label: label || undefined }) })
    weekId.value = w.id
    await load()
  } catch (e) { err.value = e.message }
}
onMounted(load)
</script>
