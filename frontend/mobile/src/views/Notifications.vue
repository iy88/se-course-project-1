<template>
  <div class="notifications-view">
    <AppNavBar title="通知中心" />

    <van-pull-refresh v-model="refreshing" @refresh="loadAll">
      <div class="view">
        <section class="surface notice-section">
          <header class="notice-section__head">
            <div>
              <h2>当前待办</h2>
            </div>
            <span class="notice-count">{{ visibleTodosTotal }}</span>
          </header>

          <div v-if="todosError" class="error-banner notice-error">
            <AppIcon name="alert" :size="17" />
            <span class="error-banner__text">{{ todosError }}</span>
            <van-button size="small" plain type="primary" @click="loadTodos">重试</van-button>
          </div>

          <div v-if="hasHiddenTradeTodos" class="alert alert--warn notice-inline">
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
              <AppIcon name="chevron-right" :size="16" class="item-arrow" />
            </button>
          </div>

          <EmptyState
            v-else-if="!todosError && todosLoaded"
            icon="check-circle"
            title="当前没有需要本人处理的事项"
          />
        </section>

        <section class="surface notice-section">
          <header class="notice-section__head">
            <div>
              <h2>通知</h2>
              <p>审核、请求、约定与处置结果</p>
            </div>
            <span v-if="unread" class="notice-unread">{{ unread }} 未读</span>
          </header>

          <div v-if="notificationsError" class="error-banner notice-error">
            <AppIcon name="alert" :size="17" />
            <span class="error-banner__text">{{ notificationsError }}</span>
            <van-button size="small" plain type="primary" @click="loadNotifications">重试</van-button>
          </div>

          <div v-if="items.length" class="notification-list">
            <button
              v-for="n in items"
              :key="n.id"
              type="button"
              class="notification-item"
              :class="{ 'notification-item--unread': !n.is_read }"
              @click="open(n)"
            >
              <span class="notification-item__icon" :class="iconTone(n.type)">
                <AppIcon :name="iconOf(n.type)" :size="18" />
              </span>
              <span class="notification-item__main">
                <span class="notification-item__top">
                  <span class="notification-item__title">{{ n.title }}</span>
                  <span v-if="!n.is_read" class="notification-item__dot" aria-hidden="true" />
                </span>
                <span v-if="n.content" class="notification-item__content">{{ n.content }}</span>
                <span class="notification-item__time">{{ fmtTime(n.created_at) }}</span>
              </span>
              <AppIcon name="chevron-right" :size="16" class="item-arrow" />
            </button>
          </div>

          <EmptyState
            v-else-if="!notificationsError && notificationsLoaded"
            icon="bell"
            title="暂无通知"
          />
        </section>
      </div>
    </van-pull-refresh>
  </div>
</template>

<script setup>
import { computed, onActivated, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import EmptyState from '../components/EmptyState.vue'
import http from '../api/http'
import { fmtTime, todoKindLabel, todoPath } from '../api/labels'
import { useSession } from '../stores/session'

const router = useRouter()
const session = useSession()
const items = ref([])
const todos = ref([])
const unread = ref(0)
const refreshing = ref(false)
const notificationsLoaded = ref(false)
const notificationsError = ref('')
const todosLoaded = ref(false)
const todosError = ref('')
const todosTotal = ref(0)

const visibleTodos = computed(() =>
  session.hasFrozenTrade ? todos.value.filter((t) => t.link_type !== 'trade') : todos.value,
)
const visibleTodosTotal = computed(() =>
  session.hasFrozenTrade ? visibleTodos.value.length : todosTotal.value,
)
const hasHiddenTradeTodos = computed(
  () => session.hasFrozenTrade && todos.value.some((t) => t.link_type === 'trade'),
)

const iconOf = (type) =>
  ({
    review_result: 'check',
    request_created: 'cart',
    request_accepted: 'check-circle',
    request_rejected: 'close',
    request_closed: 'close',
    request_withdrawn: 'refresh',
    agreement_proposed: 'edit',
    agreement_decided: 'check-circle',
    confirm_progress: 'clock',
    trade_completed: 'check-circle',
    trade_terminated: 'close',
    product_edited: 'edit',
    trade_frozen: 'alert',
    trade_dispute: 'alert',
    trade_abnormal: 'alert',
    report_result: 'shield',
    inquiry: 'info',
    disposal: 'alert',
    appeal_result: 'chat',
  }[type] || 'bell')

const iconTone = (type) => {
  if (['request_rejected', 'request_closed', 'trade_terminated', 'trade_frozen', 'trade_abnormal', 'disposal'].includes(type)) {
    return 'notification-item__icon--danger'
  }
  if (['trade_dispute', 'review_result', 'report_result'].includes(type)) {
    return 'notification-item__icon--warn'
  }
  if (['request_accepted', 'agreement_decided', 'trade_completed'].includes(type)) {
    return 'notification-item__icon--ok'
  }
  return ''
}

async function loadNotifications() {
  notificationsError.value = ''
  try {
    const data = await http.get('/notifications', { params: { page_size: 50 } })
    items.value = data.items || []
    notificationsLoaded.value = true
    const count = await http.get('/notifications/unread-count')
    unread.value = Number(count.unread || 0)
    session.unreadNotifications = unread.value
  } catch {
    notificationsError.value = '通知加载失败，请稍后重试。'
  }
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

async function loadAll() {
  try {
    await Promise.all([loadNotifications(), loadTodos()])
  } finally {
    refreshing.value = false
  }
}

function openTodo(t) {
  const path = todoPath(t)
  if (path) router.push(path)
}

async function open(n) {
  // 仅打开具体通知才已读（4.17）；已读不改变待办，待办在返回本页时重新读取。
  if (!n.is_read) {
    try {
      await http.post(`/notifications/${n.id}/read`)
      n.is_read = true
      if (unread.value > 0) unread.value -= 1
      session.unreadNotifications = unread.value
    } catch {
      return
    }
  }
  if (n.link_type === 'product') router.push(`/products/${n.link_id}`)
  else if (n.link_type === 'trade') router.push(`/trades/${n.link_id}`)
  else if (n.link_type === 'conversation') router.push(`/conversations/${n.link_id}`)
  else if (n.link_type === 'case') router.push(`/cases/${n.link_id}`)
  else if (n.link_type === 'report') router.push('/me/reports')
}

let firstActivated = false
onMounted(loadAll)
onActivated(() => {
  // keep-alive 首次激活紧接 onMounted，避免首屏重复请求；之后返回本页重新读取待办与通知。
  if (firstActivated) loadAll()
  else firstActivated = true
})
</script>

<style scoped>
.notifications-view {
  padding-bottom: 8px;
}

.notice-section {
  margin-bottom: 12px;
  overflow: hidden;
}

.notice-section__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  padding: 13px 16px 11px;
  border-bottom: 1px solid var(--line);
}

.notice-section__head h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
}

.notice-section__head p {
  margin: 1px 0 0;
  color: var(--ink-meta);
  font-size: 11.5px;
}

.notice-count {
  display: inline-grid;
  place-items: center;
  min-width: 22px;
  height: 22px;
  padding: 0 7px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand-ink);
  font-size: 11.5px;
  font-weight: 700;
}

.notice-unread {
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.notice-error {
  margin: 10px 12px;
}

.notice-inline {
  margin: 10px 12px;
}

.todo-list,
.notification-list {
  padding: 2px 0;
}

.todo-item,
.notification-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 11px 16px;
  border: 0;
  background: transparent;
  color: var(--ink);
  text-align: left;
  cursor: pointer;
}

.todo-item + .todo-item,
.notification-item + .notification-item {
  border-top: 1px solid var(--line);
}

.todo-item:active,
.notification-item:active {
  background: #f4f8f5;
}

.todo-item__icon,
.notification-item__icon {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: var(--brand-soft);
  color: var(--brand);
}

.todo-item__main,
.notification-item__main {
  display: flex;
  flex-direction: column;
  gap: 1px;
  flex: 1;
  min-width: 0;
}

.todo-item__title,
.notification-item__title {
  color: var(--ink);
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.45;
}

.todo-item__kind {
  color: var(--ink-meta);
  font-size: 11.5px;
}

.item-arrow {
  flex: 0 0 auto;
  color: var(--ink-faint);
}

.notification-item--unread {
  background: #fbfdfb;
}

.notification-item__icon--danger {
  background: var(--danger-soft);
  color: var(--danger);
}

.notification-item__icon--warn {
  background: var(--warn-soft);
  color: var(--warn);
}

.notification-item__icon--ok {
  background: var(--ok-soft);
  color: var(--ok);
}

.notification-item__top {
  display: flex;
  align-items: center;
  gap: 6px;
}

.notification-item__dot {
  flex: 0 0 auto;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--danger);
}

.notification-item__content {
  margin-top: 1px;
  color: var(--ink-soft);
  font-size: 12.5px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.notification-item__time {
  margin-top: 2px;
  color: var(--ink-meta);
  font-size: 11px;
}

@media (max-width: 359px) {
  .todo-item,
  .notification-item {
    padding-left: 12px;
    padding-right: 12px;
  }
}
</style>
