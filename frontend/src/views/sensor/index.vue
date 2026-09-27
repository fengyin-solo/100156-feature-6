<template>
  <section class="page" data-module="sensor">
    <header class="page-head">
      <div>
        <h2>观测传感器管理</h2>
        <p class="page-desc">围绕检定有效期跟踪到期情况：已过期、30 天内到期、正常三档可检索，支持按传感器编号、观测要素联合查询并按到期时间排序。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记观测传感器</button>
        <button class="btn" type="button" @click="exportRows">导出观测传感器清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="item.tone">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="applyQuery">
      <label class="filter-item">
        <span>传感器编号</span>
        <input v-model="filters.keyword" placeholder="按传感器编号检索" />
      </label>
      <label class="filter-item">
        <span>观测要素</span>
        <input v-model="filters.element" placeholder="按观测要素检索，如气温" />
      </label>
      <label class="filter-item">
        <span>到期情况</span>
        <select v-model="filters.expiry">
          <option value="">全部情况</option>
          <option v-for="bucket in expiryOptions" :key="bucket.value" :value="bucket.value">
            {{ bucket.label }}
          </option>
        </select>
      </label>
      <label class="filter-item">
        <span>到期时间排序</span>
        <select v-model="filters.sort">
          <option value="">默认顺序</option>
          <option value="expiry_asc">到期时间从近到远</option>
          <option value="expiry_desc">到期时间从远到近</option>
        </select>
      </label>
      <button class="btn primary" type="submit">查询</button>
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
          <td>{{ row['传感器编号'] ?? '—' }}</td>
          <td>{{ row['所属站点'] ?? '—' }}</td>
          <td>{{ row['观测要素'] ?? '—' }}</td>
          <td>{{ row['设备型号'] ?? '—' }}</td>
          <td>{{ row['出厂序列号'] ?? '—' }}</td>
          <td>{{ row['安装高度'] ?? '—' }}</td>
          <td>{{ row['安装日期'] || '—' }}</td>
          <td>{{ row['检定有效期'] || '—' }}</td>
          <td>
            <span v-if="row.expiryBucket" class="expiry-tag" :class="bucketTone(row.expiryBucket)">
              {{ bucketLabel(row.expiryBucket) }}
            </span>
            <span v-else class="text-muted">—</span>
          </td>
          <td>
            <span v-if="typeof row.daysLeft === 'number'" :class="daysTone(row.daysLeft)">
              {{ formatDaysLeft(row.daysLeft) }}
            </span>
            <span v-else class="text-muted">—</span>
          </td>
          <td>{{ row['传感器状态'] || row['status'] || '—' }}</td>
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
          <td :colspan="columns.length + 1" class="empty-state">{{ emptyHint }}</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>
        共 {{ total }} 条查询结果
        <template v-if="summary">
          ｜到期统计（不含已拆除 {{ summary['已拆除'] }} 台）：已过期
          <strong class="tone-expired">{{ summary['已过期'] }}</strong> 台、30 天内到期
          <strong class="tone-soon">{{ summary['30天内到期'] }}</strong> 台、正常
          <strong class="tone-normal">{{ summary['正常'] }}</strong> 台
        </template>
      </span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="createOpen" class="modal-mask" @click.self="closeCreate">
      <form class="modal-panel" @submit.prevent="submitCreate">
        <h3>登记观测传感器</h3>
        <p class="modal-tip">带 * 为必填；日期请填写真实存在的 YYYY-MM-DD，检定有效期不得早于安装日期。</p>
        <div class="form-grid">
          <label v-for="field in createFields" :key="field.name" class="form-item">
            <span>{{ field.label }}<em v-if="field.required">*</em></span>
            <input
              v-model="createForm[field.name]"
              :placeholder="field.placeholder"
              :type="field.type"
            />
          </label>
        </div>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="modal-actions">
          <button class="btn primary" type="submit">提交登记</button>
          <button class="btn ghost" type="button" @click="closeCreate">取消</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type ExpiryBucket = '已过期' | '30天内到期' | '正常'

interface SensorRow extends Record<string, unknown> {
  id: number
  daysLeft: number | null
  expiryBucket: ExpiryBucket | null
}

interface ExpirySummary {
  已过期: number
  '30天内到期': number
  正常: number
  在装传感器: number
  已拆除: number
}

interface Filters {
  keyword: string
  element: string
  expiry: string
  sort: string
}

const ENDPOINT = '/api/sensor'
const FILTER_STORAGE_KEY = 'sensor:filters'
const columns = [
  '传感器编号', '所属站点', '观测要素', '设备型号', '出厂序列号',
  '安装高度', '安装日期', '检定有效期', '到期情况', '剩余天数', '传感器状态',
]
const actions = ['安排检定', '标记疑误', '拆除传感器']
const expiryOptions: { value: ExpiryBucket; label: string }[] = [
  { value: '已过期', label: '已过期' },
  { value: '30天内到期', label: '30 天内到期' },
  { value: '正常', label: '正常' },
]

const rows = ref<SensorRow[]>([])
const total = ref(0)
const summary = ref<ExpirySummary | null>(null)
const errorMessage = ref('')
const filters = ref<Filters>({ keyword: '', element: '', expiry: '', sort: '' })

const createOpen = ref(false)
const createError = ref('')
interface CreateField {
  name: string
  label: string
  required: boolean
  type: string
  placeholder: string
}

const createFields: CreateField[] = [
  { name: '传感器编号', label: '传感器编号', required: true, type: 'text', placeholder: '如 SENS-0010' },
  { name: '所属站点', label: '所属站点', required: true, type: 'text', placeholder: '如 滨江国家基本气象站' },
  { name: '观测要素', label: '观测要素', required: true, type: 'text', placeholder: '如 气温' },
  { name: '设备型号', label: '设备型号', required: false, type: 'text', placeholder: '可选' },
  { name: '出厂序列号', label: '出厂序列号', required: false, type: 'text', placeholder: '可选' },
  { name: '安装高度', label: '安装高度', required: false, type: 'text', placeholder: '如 1.5m' },
  { name: '安装日期', label: '安装日期', required: true, type: 'text', placeholder: 'YYYY-MM-DD' },
  { name: '检定有效期', label: '检定有效期', required: true, type: 'text', placeholder: 'YYYY-MM-DD' },
]
const emptyCreateForm = (): Record<string, string> => ({
  传感器编号: '', 所属站点: '', 观测要素: '', 设备型号: '',
  出厂序列号: '', 安装高度: '', 安装日期: '', 检定有效期: '',
})
const createForm = ref<Record<string, string>>(emptyCreateForm())

const statCards = computed(() => {
  const s = summary.value
  return [
    { label: '在装传感器', value: s ? s['在装传感器'] : 0, tone: '' },
    { label: '已过期', value: s ? s['已过期'] : 0, tone: 'tone-expired' },
    { label: '30 天内到期', value: s ? s['30天内到期'] : 0, tone: 'tone-soon' },
    { label: '正常', value: s ? s['正常'] : 0, tone: 'tone-normal' },
  ]
})

const emptyHint = computed(() => {
  const active = [filters.value.keyword, filters.value.element, filters.value.expiry].some((v) => v.trim())
  return active
    ? '没有符合当前查询条件的观测传感器，请调整编号、观测要素或到期情况后重试'
    : '暂无观测传感器数据，可先登记观测传感器'
})

function bucketLabel(bucket: string): string {
  return expiryOptions.find((item) => item.value === bucket)?.label ?? bucket
}

function bucketTone(bucket: string | null): string {
  if (bucket === '已过期') return 'tone-expired'
  if (bucket === '30天内到期') return 'tone-soon'
  return 'tone-normal'
}

function daysTone(daysLeft: number): string {
  if (daysLeft < 0) return 'tone-expired'
  if (daysLeft <= 30) return 'tone-soon'
  return 'tone-normal'
}

function formatDaysLeft(daysLeft: number): string {
  if (daysLeft < 0) return `已逾期 ${Math.abs(daysLeft)} 天`
  if (daysLeft === 0) return '今日到期'
  return `剩余 ${daysLeft} 天`
}

function saveFilters() {
  // 从别的页面返回或整页刷新后，用它恢复查询条件，再重新拉取剩余天数
  sessionStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(filters.value))
}

function restoreFilters() {
  const raw = sessionStorage.getItem(FILTER_STORAGE_KEY)
  if (!raw) return
  try {
    const saved = JSON.parse(raw) as Partial<Filters>
    filters.value = {
      keyword: typeof saved.keyword === 'string' ? saved.keyword : '',
      element: typeof saved.element === 'string' ? saved.element : '',
      expiry: typeof saved.expiry === 'string' ? saved.expiry : '',
      sort: typeof saved.sort === 'string' ? saved.sort : '',
    }
  } catch {
    sessionStorage.removeItem(FILTER_STORAGE_KEY)
  }
}

function applyQuery() {
  saveFilters()
  void reload()
}

function resetFilters() {
  filters.value = { keyword: '', element: '', expiry: '', sort: '' }
  sessionStorage.removeItem(FILTER_STORAGE_KEY)
  void reload()
}

function exportRows() {
  const query = new URLSearchParams(buildParams()).toString()
  window.open(`${ENDPOINT}/export?${query}`, '_blank')
}

function buildParams(): Record<string, string> {
  const params: Record<string, string> = { page: '1', size: '200' }
  if (filters.value.keyword.trim()) params.keyword = filters.value.keyword.trim()
  if (filters.value.element.trim()) params.element = filters.value.element.trim()
  if (filters.value.expiry) params.expiry = filters.value.expiry
  if (filters.value.sort) params.sort = filters.value.sort
  return params
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(buildParams()).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { detail?: string } | null
      throw new Error(payload?.detail ?? '观测传感器列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    // 统计卡片与页脚共用同一份 summary，保证两处到期条数完全一致
    summary.value = payload.summary ?? null
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '观测传感器列表读取失败'
  }
}

function openCreate() {
  createForm.value = emptyCreateForm()
  createError.value = ''
  createOpen.value = true
}

function closeCreate() {
  createOpen.value = false
}

/** 严格解析 YYYY-MM-DD：2026-02-30、2026-13-01 这类不存在的日期直接判为不合法。 */
function parseStrictDate(raw: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw.trim())
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (month < 1 || month > 12 || day < 1 || day > 31) return null
  const date = new Date(year, month - 1, day)
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
    return null
  }
  return date
}

function validateCreate(): string {
  const required = ['传感器编号', '所属站点', '观测要素', '安装日期', '检定有效期']
  const missing = required.filter((name) => !createForm.value[name]?.trim())
  if (missing.length) return `以下必填项未填写：${missing.join('、')}`

  const installRaw = createForm.value['安装日期'].trim()
  const expiryRaw = createForm.value['检定有效期'].trim()
  const installDate = parseStrictDate(installRaw)
  if (!installDate) return `安装日期「${installRaw}」不是有效日期，请填写真实存在的日期（格式 YYYY-MM-DD，如 2026-09-27）`
  const expiryDate = parseStrictDate(expiryRaw)
  if (!expiryDate) return `检定有效期「${expiryRaw}」不是有效日期，请填写真实存在的日期（格式 YYYY-MM-DD，如 2026-09-27）`
  if (expiryDate < installDate) {
    return `检定有效期「${expiryRaw}」早于安装日期「${installRaw}」，检定有效期不能早于安装日期，请核对后重新填写`
  }
  return ''
}

async function submitCreate() {
  createError.value = ''
  const validationError = validateCreate()
  if (validationError) {
    createError.value = validationError
    return
  }
  const values: Record<string, string> = {}
  for (const field of createFields) {
    const value = createForm.value[field.name]?.trim()
    if (value) values[field.name] = value
  }
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || payload?.detail || '观测传感器登记失败，请稍后重试')
    }
    createOpen.value = false
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '观测传感器登记失败'
  }
}

async function runAction(action: string, row: SensorRow) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '观测传感器动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '观测传感器操作失败'
  }
}

onMounted(() => {
  restoreFilters()
  void reload()
})
</script>
