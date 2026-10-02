<template>
  <div>
    <h1 class="brand">本周看板</h1>
    <p class="muted">周卡片网格 · round-robin 落位后可去「对调」申请交换 · 跳过周空档但相位照走</p>

    <div class="week-list" v-if="weeks.length">
      <button v-for="w in weeks" :key="w.id"
              class="ghost week-pick"
              :class="{ active: w.id === weekId }"
              @click="pick(w.id)">
        #{{ w.id }} {{ w.label }}
        <span class="chip" :class="statusChip(w.status)">{{ statusText(w.status) }}</span>
      </button>
      <button class="ghost week-pick" @click="addWeek">＋新一周</button>
    </div>

    <div class="week-head">
      <h2>{{ week ? '#'+week.id+' '+week.label : '—' }}
        <span v-if="week" class="chip" :class="statusChip(week.status)">{{ statusText(week.status) }}</span>
      </h2>
    </div>

    <div style="display:flex;gap:8px;margin:12px 0;flex-wrap:wrap">
      <button @click="generate" :disabled="isSkipped">生成周表</button>
      <button v-if="!isSkipped" class="ghost" @click="skip">跳过本周</button>
      <button v-else class="ghost" @click="unskip">取消跳过</button>
      <button class="ghost" @click="load">刷新</button>
    </div>
    <p v-if="isSkipped" class="skip-note">
      本周已跳过：不生成排班，空档展示；round-robin 相位按 {{ week.phase_start }} 起的 {{ week.grid_size ?? '—' }} 格继续前进，后续周照常承接。
    </p>
    <p v-if="err" class="err">{{ err }}</p>

    <div class="week-grid">
      <article v-for="d in days" :key="d" class="week-card" :class="{ skipped: isSkipped }">
        <header>Day {{ d }}</header>
        <template v-if="!isSkipped">
          <div v-for="a in byDay(d)" :key="a.id">
            <span class="chip">{{ a.task_title }}</span>
            <span class="chip coral">{{ a.member_name }}</span>
          </div>
          <p v-if="!byDay(d).length" class="muted">空</p>
        </template>
        <p v-else class="muted skip-cell">跳过</p>
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
const days = [0,1,2,3,4,5,6]
const err = ref('')
const weekId = ref(1)
const isSkipped = computed(() => week.value && week.value.status === 'skipped')

const STATUS_TEXT = { draft: '草稿', ready: '已生成', skipped: '已跳过' }
function statusText(s) { return STATUS_TEXT[s] || s }
function statusChip(s) { return s === 'skipped' ? 'coral' : '' }

function byDay(d) { return assigns.value.filter(a => a.day === d) }

async function loadWeeks(selectId) {
  const rows = await api('/weeks')
  weeks.value = rows
  if (!rows.some(w => w.id === weekId.value)) weekId.value = (rows[rows.length - 1] || {}).id || 1
  if (selectId) weekId.value = selectId
}

async function load() {
  err.value = ''
  try {
    await loadWeeks()
    const b = await api('/weeks/' + weekId.value + '/board')
    week.value = b.week
    assigns.value = b.assignments || []
  } catch (e) { err.value = e.message }
}

async function pick(id) {
  weekId.value = id
  await load()
}

async function addWeek() {
  err.value = ''
  try {
    const w = await api('/weeks', { method: 'POST', body: JSON.stringify({ label: '第' + (weeks.value.length + 1) + '周' }) })
    await load(w.id)
  } catch (e) { err.value = e.message }
}

async function generate() {
  err.value = ''
  try { await api('/weeks/' + weekId.value + '/generate', { method: 'POST', body: '{}' }); await load() }
  catch (e) { err.value = e.message }
}

async function skip() {
  err.value = ''
  const filled = assigns.value.length
  const msg = filled
    ? `本周已有 ${filled} 个排班格子，跳过后将清空这些格子并作废其待确认对调，相位仍按应有格数前进。确定跳过？`
    : '跳过本周？本周不生成排班，但 round-robin 相位照常前进。'
  if (!window.confirm(msg)) return
  try { await api('/weeks/' + weekId.value + '/skip', { method: 'POST', body: '{}' }); await load() }
  catch (e) { err.value = e.message }
}

async function unskip() {
  err.value = ''
  try { await api('/weeks/' + weekId.value + '/unskip', { method: 'POST', body: '{}' }); await load() }
  catch (e) { err.value = e.message }
}

onMounted(load)
</script>
