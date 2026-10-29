<template>
  <div class="me-view">
    <AppNavBar title="我的" :back="false" />

    <div class="view">
      <section class="surface profile">
        <div class="avatar-text profile__avatar">{{ initial }}</div>
        <div class="profile__main">
          <div class="profile__name-row">
            <h1>{{ session.user?.display_name || '未登录用户' }}</h1>
            <span v-if="session.user?.status === 'banned'" class="pill pill--danger">封禁中</span>
            <span v-else-if="session.user?.has_frozen_trade" class="pill pill--warn">交易冻结中</span>
          </div>
          <p class="profile__email">{{ session.user?.email }}</p>
        </div>
        <div class="profile__actions">
          <button type="button" class="profile__settings" aria-label="账户设置" @click="router.push('/me/settings')">
            <AppIcon name="settings" :size="20" />
          </button>
          <button type="button" class="profile__logout" aria-label="退出登录" @click="logout">
            <AppIcon name="logout" :size="20" />
            <span>退出登录</span>
          </button>
        </div>
      </section>

      <div v-if="session.user?.has_frozen_trade && session.user?.status !== 'banned'" class="alert alert--warn">
        <AppIcon name="alert" :size="17" />
        <span>交易冻结期间禁止发布新商品、主动上下架；无关商品合规编辑、收藏与管理沟通仍可用。</span>
      </div>
      <div v-if="session.user?.status === 'banned'" class="alert alert--danger">
        <AppIcon name="alert" :size="17" />
        <span>账户封禁中：业务写操作暂停，本人记录只读；处置通知与沟通单仍可用于说明/申辩。</span>
      </div>

      <section class="surface me-section">
        <header class="me-section__head">
          <h2>当前待办</h2>
          <span class="me-count">{{ visibleTodosTotal }}</span>
        </header>

        <div v-if="todosError" class="error-banner me-error">
          <AppIcon name="alert" :size="17" />
          <span class="error-banner__text">{{ todosError }}</span>
          <van-button size="small" plain type="primary" @click="loadTodos">重试</van-button>
        </div>

        <div v-if="hasHiddenTradeTodos" class="alert alert--warn me-inline-alert">
          <AppIcon name="info" :size="16" />
          <span>交易冻结期间暂不显示交易操作待办；解冻后返回本页刷新即可恢复。</span>
        </div>

        <div v-if="visibleTodos.length" class="todo-list">
          <button v-for="t in visibleTodos" :key="t.key" type="button" class="todo-item" @click="openTodo(t)">
            <span class="todo-item__icon"><AppIcon name="clock" :size="18" /></span>
            <span class="todo-item__main">
              <span class="todo-item__title">{{ t.title }}</span>
              <span class="todo-item__kind">{{ todoKindLabel(t.kind) }}</span>
            </span>
            <AppIcon name="chevron-right" :size="16" class="todo-item__arrow" />
          </button>
        </div>

        <EmptyState
          v-else-if="!todosError && todosLoaded"
          icon="check-circle"
          title="当前没有需要本人处理的事项"
        />

        <button type="button" class="notice-link" @click="router.push('/notifications')">
          <span class="notice-link__icon"><AppIcon name="bell" :size="18" /></span>
          <span class="notice-link__label">通知未读</span>
          <span class="notice-link__value" :class="{ 'notice-link__value--error': notificationsError }">
            {{ notificationsError ? '加载失败，可重试' : `${unread} 条` }}
          </span>
          <AppIcon name="chevron-right" :size="16" class="todo-item__arrow" />
        </button>
      </section>

      <section class="surface me-section">
        <header class="me-section__head">
          <h2>本人业务</h2>
        </header>
        <nav class="menu-list" aria-label="本人业务">
          <router-link v-for="item in businessMenu" :key="item.to" :to="item.to" class="menu-item">
            <span class="menu-item__icon"><AppIcon :name="item.icon" :size="19" /></span>
            <span class="menu-item__label">{{ item.label }}</span>
            <AppIcon name="chevron-right" :size="16" class="menu-item__arrow" />
          </router-link>
        </nav>
      </section>

      <section class="surface me-section">
        <header class="me-section__head">
          <h2>管理沟通</h2>
          <span class="me-section__sub">处置通知与沟通单</span>
        </header>

        <div v-if="casesError" class="error-banner me-error">
          <AppIcon name="alert" :size="17" />
          <span class="error-banner__text">{{ casesError }}</span>
          <van-button size="small" plain type="primary" @click="loadCases">重试</van-button>
        </div>

        <div v-if="myCases.length" class="case-list">
          <router-link v-for="c in myCases" :key="c.id" :to="`/cases/${c.id}`" class="case-item">
            <div class="case-item__main">
              <p class="case-item__title">{{ c.title }}</p>
              <p class="case-item__meta">
                <span>{{ caseTypeLabels[c.case_type] }}</span>
                <span class="case-item__dot" aria-hidden="true">·</span>
                <span>{{ caseStatusLabels[c.status] }}</span>
              </p>
            </div>
            <AppIcon name="chevron-right" :size="16" class="case-item__arrow" />
          </router-link>
        </div>

        <EmptyState
          v-else-if="!casesError && casesLoaded"
          icon="shield"
          title="暂无相关事项"
        />
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onActivated, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import EmptyState from '../components/EmptyState.vue'
import http from '../api/http'
import { caseTypeLabels, caseStatusLabels, todoKindLabel, todoPath } from '../api/labels'
import { useSession } from '../stores/session'

const router = useRouter()
const session = useSession()
const myCases = ref([])
const casesLoaded = ref(false)
const casesError = ref('')
const todos = ref([])
const todosLoaded = ref(false)
const todosError = ref('')
const todosTotal = ref(0)
const unread = ref(0)
const notificationsError = ref('')

const businessMenu = [
  { to: '/me/products', label: '我的商品', icon: 'box' },
  { to: '/me/trades', label: '我的交易', icon: 'swap' },
  { to: '/me/favorites', label: '我的收藏', icon: 'star' },
  { to: '/me/reviews', label: '我的评价', icon: 'comment' },
  { to: '/me/reports', label: '我的举报 / 我收到的举报', icon: 'shield' },
]

const initial = computed(() => {
  const name = session.user?.display_name || ''
  return name ? Array.from(name)[0] : '我'
})

const visibleTodos = computed(() =>
  session.hasFrozenTrade ? todos.value.filter((t) => t.link_type !== 'trade') : todos.value,
)
const visibleTodosTotal = computed(() =>
  session.hasFrozenTrade ? visibleTodos.value.length : todosTotal.value,
)
const hasHiddenTradeTodos = computed(
  () => session.hasFrozenTrade && todos.value.some((t) => t.link_type === 'trade'),
)

async function logout() {
  await showConfirmDialog({ title: '退出登录' })
  await http.post('/auth/logout').catch(() => {})
  session.clear()
  showToast('已退出登录')
  router.replace('/auth/login')
}

function openTodo(t) {
  const path = todoPath(t)
  if (path) router.push(path)
}

async function loadTodos() {
  todosError.value = ''
  try {
    const data = await http.get('/notifications/todos')
    todos.value = data.items || []
    todosTotal.value = Number(data.total ?? todos.value.length)
    todosLoaded.value = true
  } catch {
    todosError.value = '待办加载失败，请稍后重试。'
  }
}

async function loadUnread() {
  notificationsError.value = ''
  try {
    const data = await http.get('/notifications/unread-count')
    unread.value = Number(data.unread || 0)
    session.unreadNotifications = unread.value
  } catch {
    notificationsError.value = '未读通知加载失败，请稍后重试。'
  }
}

async function loadCases() {
  casesError.value = ''
  try {
    myCases.value = await http.get('/me/cases')
    casesLoaded.value = true
  } catch {
    casesError.value = '管理沟通事项加载失败，请稍后重试。'
  }
}

function loadAll() {
  // 路由 afterEach 与页面激活都会刷新账户限制；store 合并并发请求，既避免重复风暴又保留实时资格。
  session.refreshUser().catch(() => {})
  loadTodos()
  loadUnread()
  loadCases()
}

let firstActivated = false
onMounted(loadAll)
onActivated(() => {
  // keep-alive 首次激活紧接 onMounted，避免首屏重复请求；之后返回本页重新读取。
  if (firstActivated) loadAll()
  else firstActivated = true
})
</script>

<style scoped>
.me-view {
  padding-bottom: 8px;
}

.profile {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 16px;
}

.profile__avatar {
  width: 56px;
  height: 56px;
  font-size: 22px;
}

.profile__main {
  flex: 1 1 150px;
  min-width: 0;
}

.profile__name-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.profile__name-row h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile__email {
  margin: 2px 0 0;
  color: var(--ink-meta);
  font-size: 12.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
  min-width: 0;
  margin-left: auto;
}

.profile__settings {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 38px;
  height: 38px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #f7f9f7;
  color: var(--ink-soft);
  cursor: pointer;
}

.profile__settings:active {
  border-color: var(--brand);
  color: var(--brand);
}

.profile__logout {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex: 0 0 auto;
  height: 38px;
  padding: 0 12px;
  border: 1px solid var(--danger-soft);
  border-radius: 10px;
  background: var(--danger-soft);
  color: var(--danger);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
}

.profile__logout:active {
  border-color: var(--danger);
}

.me-section {
  margin-top: 12px;
  overflow: hidden;
}

.me-section__head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 13px 16px 11px;
  border-bottom: 1px solid var(--line);
}

.me-section__head h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
}

.me-section__sub {
  color: var(--ink-meta);
  font-size: 11.5px;
}

.me-count {
  display: inline-grid;
  place-items: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand-ink);
  font-size: 11px;
  font-weight: 700;
}

.me-error {
  margin: 10px 12px;
}

.me-inline-alert {
  margin: 10px 12px;
}

.todo-list {
  padding: 4px 0;
}

.todo-item,
.notice-link {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 11px 16px;
  border: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.todo-item + .todo-item {
  border-top: 1px solid var(--line);
}

.todo-item:active,
.notice-link:active {
  background: #f4f8f5;
}

.todo-item__icon,
.notice-link__icon {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: var(--brand-soft);
  color: var(--brand);
}

.todo-item__main {
  display: flex;
  flex-direction: column;
  gap: 1px;
  flex: 1;
  min-width: 0;
}

.todo-item__title {
  color: var(--ink);
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.45;
}

.todo-item__kind {
  color: var(--ink-meta);
  font-size: 11.5px;
}

.todo-item__arrow,
.menu-item__arrow,
.case-item__arrow {
  flex: 0 0 auto;
  color: var(--ink-faint);
}

.notice-link {
  border-top: 1px solid var(--line);
}

.notice-link__label {
  flex: 1;
  font-size: 13.5px;
  font-weight: 600;
}

.notice-link__value {
  color: var(--ink-meta);
  font-size: 12.5px;
}

.notice-link__value--error {
  color: var(--danger);
}

.menu-list {
  padding: 2px 0;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 12px 16px;
  border: 0;
  background: transparent;
  color: var(--ink);
  text-align: left;
  text-decoration: none;
  cursor: pointer;
}

.menu-item + .menu-item {
  border-top: 1px solid var(--line);
}

.menu-item:active {
  background: #f4f8f5;
}

.menu-item__icon {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: #f1f5f2;
  color: var(--ink-soft);
}

.menu-item__label {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 500;
}

.case-list {
  padding: 2px 0;
}

.case-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 16px;
  color: var(--ink);
  text-decoration: none;
}

.case-item + .case-item {
  border-top: 1px solid var(--line);
}

.case-item:active {
  background: #f4f8f5;
}

.case-item__main {
  flex: 1;
  min-width: 0;
}

.case-item__title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.45;
}

.case-item__meta {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 2px 0 0;
  color: var(--ink-meta);
  font-size: 11.5px;
}

.case-item__dot {
  color: var(--line-strong);
}

@media (max-width: 359px) {
  .profile {
    padding: 14px 12px;
  }

  .profile__avatar {
    width: 48px;
    height: 48px;
    font-size: 19px;
  }

  .todo-item,
  .notice-link,
  .menu-item,
  .case-item {
    padding-left: 12px;
    padding-right: 12px;
  }
}
</style>
