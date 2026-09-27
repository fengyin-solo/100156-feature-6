<template>
  <section class="page" data-module="sensor">
    <header class="page-head">
      <div>
        <h2>观测传感器管理</h2>
        <p class="page-desc">维护观测传感器，按检定有效期把设备分成已过期、30天内到期、正常三类，支持检索、排序与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记观测传感器</button>
        <button class="btn" type="button" @click="exportRows">导出观测传感器清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="applyFilters">
      <label class="filter-item">
        <span>传感器编号</span>
        <input v-model="filters.keyword" placeholder="按传感器编号检索" />
      </label>
      <label class="filter-item">
        <span>观测要素</span>
        <input v-model="filters.element" placeholder="按观测要素检索" />
      </label>
      <label class="filter-item">
        <span>到期情况</span>
        <select v-model="filters.expiry">
          <option value="">全部</option>
          <option v-for="bucket in expiryBuckets" :key="bucket" :value="bucket">{{ bucket }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>到期排序</span>
        <select v-model="filters.sort">
          <option value="">默认顺序</option>
          <option value="asc">到期从近到远</option>
          <option value="desc">到期从远到近</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '剩余天数'">{{ formatDays(row[column]) }}</template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">{{ emptyText }}</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条观测传感器记录</span>
      <span>
        到期统计（不含已拆除）：已过期 {{ expiryStats['已过期'] }} 条 ·
        30天内到期 {{ expiryStats['30天内到期'] }} 条 · 正常 {{ expiryStats['正常'] }} 条
      </span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="calibrationTarget" class="dialog-mask" @click.self="closeCalibration">
      <form class="dialog" @submit.prevent="submitCalibration">
        <h3 class="dialog-title">安排检定 · {{ calibrationTarget['传感器编号'] }}</h3>
        <p class="dialog-desc">
          安装日期：{{ calibrationTarget['安装日期'] ?? '—' }}，检定有效期不能早于安装日期。
        </p>
        <label class="filter-item">
          <span>检定有效期</span>
          <input v-model="calibrationDue" placeholder="例如 2027-09-30" />
        </label>
        <p v-if="calibrationError" class="error-text">{{ calibrationError }}</p>
        <div class="dialog-actions">
          <button class="btn primary" type="submit">确认安排</button>
          <button class="btn ghost" type="button" @click="closeCalibration">取消</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/sensor'
const columns = ["传感器编号", "所属站点", "观测要素", "设备型号", "出厂序列号", "安装高度", "安装日期", "检定有效期", "到期情况", "剩余天数", "传感器状态"]
const actions = ["安排检定", "标记疑误", "拆除传感器"]
const expiryBuckets = ["已过期", "30天内到期", "正常"]
const sortOptions = ["asc", "desc"]

const route = useRoute()
const router = useRouter()

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const stats = ref([
  { label: '已过期', value: 0 },
  { label: '30天内到期', value: 0 },
  { label: '正常（30天以上）', value: 0 },
])
const expiryStats = ref<Record<string, number>>({ '已过期': 0, '30天内到期': 0, '正常': 0 })
const filters = reactive({ keyword: '', element: '', expiry: '', sort: '' })

const calibrationTarget = ref<Row | null>(null)
const calibrationDue = ref('')
const calibrationError = ref('')

const hasActiveFilters = computed(
  () => Boolean(filters.keyword || filters.element || filters.expiry || filters.sort),
)
const emptyText = computed(() =>
  hasActiveFilters.value
    ? '没有符合条件的观测传感器，请调整传感器编号、观测要素或到期情况后重新查询'
    : '暂无观测传感器数据，可先登记观测传感器',
)

function formatDays(value: Row[string]): string {
  if (value === null || value === undefined || value === '') return '—'
  const days = Number(value)
  if (Number.isNaN(days)) return '—'
  return days < 0 ? `已超期 ${-days} 天` : `剩余 ${days} 天`
}

function parseDateInput(text: string): Date | null {
  const match = /^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$/.exec(text.trim())
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const parsed = new Date(year, month - 1, day)
  // 拒绝 2026-02-30、2026-13-01 这类会被 Date 自动进位的不存在日期
  if (parsed.getFullYear() !== year || parsed.getMonth() !== month - 1 || parsed.getDate() !== day) {
    return null
  }
  return parsed
}

function syncQuery() {
  const query: Record<string, string> = {}
  if (filters.keyword) query.keyword = filters.keyword
  if (filters.element) query.element = filters.element
  if (filters.expiry) query.expiry = filters.expiry
  if (filters.sort) query.sort = filters.sort
  void router.replace({ query })
}

function applyFilters() {
  syncQuery()
  void reload()
}

function resetFilters() {
  filters.keyword = ''
  filters.element = ''
  filters.expiry = ''
  filters.sort = ''
  syncQuery()
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '观测传感器登记入口尚未接入审批流'
}

function runAction(action: string, row: Row) {
  if (action === '安排检定') {
    calibrationTarget.value = row
    calibrationDue.value = String(row['检定有效期'] ?? '')
    calibrationError.value = ''
    return
  }
  if (action === '拆除传感器' && !window.confirm(`确认拆除传感器 ${row['传感器编号']}？拆除后不再参与到期统计。`)) {
    return
  }
  void postAction(action, row)
}

function closeCalibration() {
  calibrationTarget.value = null
  calibrationDue.value = ''
  calibrationError.value = ''
}

async function submitCalibration() {
  const row = calibrationTarget.value
  if (!row) return
  calibrationError.value = ''
  const dueText = calibrationDue.value.trim()
  if (!dueText) {
    calibrationError.value = '请填写检定有效期'
    return
  }
  const due = parseDateInput(dueText)
  if (!due) {
    calibrationError.value = `检定有效期「${dueText}」不是有效日期，请检查月份或日期是否存在`
    return
  }
  const installedText = String(row['安装日期'] ?? '')
  const installed = parseDateInput(installedText)
  if (installed && due.getTime() < installed.getTime()) {
    calibrationError.value = `检定有效期 ${dueText} 早于安装日期 ${installedText}，请核对后再提交`
    return
  }
  const ok = await postAction('安排检定', row, { 检定有效期: dueText })
  if (ok) {
    closeCalibration()
  } else {
    calibrationError.value = errorMessage.value
  }
}

async function postAction(action: string, row: Row, extra: Record<string, string> = {}): Promise<boolean> {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, ...extra } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(payload?.detail ?? '观测传感器动作未生效，请稍后重试')
    }
    if (payload && payload.ok === false) {
      throw new Error(payload.message ?? '观测传感器动作未生效，请稍后重试')
    }
    await reload()
    return true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '观测传感器操作失败'
    return false
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (filters.keyword) params.set('keyword', filters.keyword)
  if (filters.element) params.set('element', filters.element)
  if (filters.expiry) params.set('expiry', filters.expiry)
  if (filters.sort) params.set('sort', filters.sort)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    const payload = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(payload?.detail ?? '观测传感器列表读取失败')
    }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    const statsPayload = (payload.stats ?? {}) as Record<string, number>
    expiryStats.value = {
      '已过期': Number(statsPayload['已过期'] ?? 0),
      '30天内到期': Number(statsPayload['30天内到期'] ?? 0),
      '正常': Number(statsPayload['正常'] ?? 0),
    }
    stats.value = [
      { label: '已过期', value: expiryStats.value['已过期'] },
      { label: '30天内到期', value: expiryStats.value['30天内到期'] },
      { label: '正常（30天以上）', value: expiryStats.value['正常'] },
    ]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '观测传感器列表读取失败'
  }
}

onMounted(() => {
  // 从地址栏恢复查询条件：从别的页面返回或刷新后，列表与剩余天数保持进入前的状态
  const query = route.query
  filters.keyword = String(query.keyword ?? '')
  filters.element = String(query.element ?? '')
  const expiry = String(query.expiry ?? '')
  filters.expiry = expiryBuckets.includes(expiry) ? expiry : ''
  const sort = String(query.sort ?? '')
  filters.sort = sortOptions.includes(sort) ? sort : ''
  void reload()
})
</script>
