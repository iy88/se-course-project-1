<template>
  <el-container class="app-shell">
    <el-aside :width="asideWidth" class="side" :class="{ compact }">
      <div class="brand">
        <span class="brand-mark"><AppIcon name="brand" :size="22" /></span>
        <span v-if="!compact" class="brand-text">
          <strong>校园二手</strong>
          <small>管理端</small>
        </span>
      </div>

      <el-menu
        :default-active="activeMenu"
        :default-openeds="defaultOpeneds"
        router
        :collapse="compact"
        :collapse-transition="false"
        background-color="#1e2f28"
        text-color="#b9c9c0"
        active-text-color="#ffffff"
        class="side-menu"
      >
        <template v-for="section in navSections" :key="section.key || section.path">
          <el-sub-menu v-if="section.children" :index="section.key">
            <template #title>
              <el-icon :size="18"><AppIcon :name="section.icon" /></el-icon>
              <span class="nav-label">{{ section.label }}</span>
            </template>
            <el-menu-item v-for="item in section.children" :key="item.path" :index="item.path" :title="item.label">
              <el-icon :size="18"><AppIcon :name="item.icon" /></el-icon>
              <template #title><span class="nav-label">{{ item.label }}</span></template>
            </el-menu-item>
          </el-sub-menu>
          <el-menu-item v-else :index="section.path" :title="section.label">
            <el-icon :size="18"><AppIcon :name="section.icon" /></el-icon>
            <template #title><span class="nav-label">{{ section.label }}</span></template>
          </el-menu-item>
        </template>
      </el-menu>

      <div v-if="!compact" class="side-foot">
        <span>平台管理控制台</span>
        <span class="side-foot-sub">仅授权管理员访问</span>
      </div>
    </el-aside>

    <el-container class="main-col">
      <el-header class="topbar">
        <nav class="crumb" aria-label="面包屑">
          <span>管理端</span>
          <el-icon class="crumb-sep" :size="12"><AppIcon name="next" /></el-icon>
          <button v-if="parentCrumb" type="button" class="crumb-link" @click="router.push(parentCrumb.path)">
            {{ parentCrumb.label }}
          </button>
          <el-icon v-if="parentCrumb" class="crumb-sep" :size="12"><AppIcon name="next" /></el-icon>
          <strong class="current" aria-current="page">{{ currentTitle }}</strong>
        </nav>

        <div class="account">
          <span class="avatar" aria-hidden="true"><img v-if="session.user?.avatar_url" :src="session.user.avatar_url" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:inherit" /><span v-else>{{ initial }}</span></span>
          <span class="account-meta">
            <strong>{{ adminName }}</strong>
            <small>平台管理员</small>
          </span>
          <el-button class="logout-button" plain @click="logout">
            <el-icon><AppIcon name="logout" /></el-icon>
            <span>退出</span>
          </el-button>
        </div>
      </el-header>

      <div v-if="isNarrow" class="narrow-note">
        窗口较窄，侧栏已自动收起；建议在 1280px 以上宽度处理表格与交易详情。
      </div>

      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import { useSession } from '../stores/session'

const route = useRoute()
const router = useRouter()
const session = useSession()
const adminName = computed(() => session.user?.display_name || '管理员')
const windowWidth = ref(typeof window === 'undefined' ? 1280 : window.innerWidth)

const navSections = [
  {
    key: 'review',
    label: '事项审核',
    icon: 'cases',
    children: [
      { path: '/cases', label: '待处理池', icon: 'menu' },
      { path: '/my-cases', label: '我的审核', icon: 'user' },
    ],
  },
  { path: '/products', label: '商品管理', icon: 'products' },
  { path: '/users', label: '账户管理', icon: 'users' },
  { path: '/categories', label: '分类标签', icon: 'categories' },
  { path: '/prohibited', label: '禁发范围', icon: 'prohibited' },
  { path: '/audit', label: '审计查询', icon: 'shield' },
  { path: '/stats', label: '数据统计', icon: 'stats' },
]

const defaultOpeneds = ['review']

const compact = computed(() => windowWidth.value < 1080)
const isNarrow = computed(() => windowWidth.value < 900)
const asideWidth = computed(() => {
  if (compact.value) return '76px'
  return windowWidth.value < 1280 ? '212px' : '232px'
})
const currentTitle = computed(() => route.meta.title || '管理端')
const activeMenu = computed(() => {
  if (route.path.startsWith('/cases/')) return route.query.from === 'my-cases' ? '/my-cases' : '/cases'
  if (route.path.startsWith('/products/')) return '/products'
  return route.path
})
const parentCrumb = computed(() => {
  if (route.path.startsWith('/cases/')) {
    if (route.query.from === 'my-cases') return { label: '我的审核', path: '/my-cases' }
    return { label: '待处理池', path: '/cases' }
  }
  if (route.path.startsWith('/products/')) return { label: '商品管理', path: '/products' }
  return null
})
const initial = computed(() => (adminName.value || '管理员').trim().slice(0, 1) || '管')

function onResize() {
  windowWidth.value = window.innerWidth
}

onMounted(() => {
  onResize()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
})

function logout() {
  session.clear()
  router.push('/login')
}
</script>

<style scoped>
.app-shell {
  height: 100%;
  background: var(--bg);
}

.side {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #1e2f28;
  border-right: 1px solid #2a4035;
  transition: width 0.16s ease;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 64px;
  padding: 14px 16px;
}

.compact .brand {
  justify-content: center;
  padding: 14px 0;
}

.brand-mark {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: var(--brand);
  color: #fff;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14);
}

.brand-text {
  min-width: 0;
}

.brand-text strong {
  display: block;
  color: #fff;
  font-size: 14px;
  font-weight: 650;
  letter-spacing: 0.02em;
  line-height: 1.3;
}

.brand-text small {
  display: block;
  color: #9fb5a9;
  font-size: 10.5px;
  letter-spacing: 0.16em;
}

.side-menu {
  flex: 1;
  border-right: 0;
  padding: 6px 10px;
  overflow-y: auto;
  overflow-x: hidden;
}

.side-menu.el-menu--collapse {
  width: 56px;
  margin: 0 auto;
  padding: 6px 0;
}

.side-menu :deep(.el-menu-item) {
  height: 42px;
  line-height: 42px;
  margin: 2px 0;
  border-radius: 8px;
  color: #b9c9c0;
  font-size: 13px;
}

.side-menu :deep(.el-sub-menu__title) {
  height: 42px;
  line-height: 42px;
  margin: 2px 0;
  border-radius: 8px;
  color: #b9c9c0;
  font-size: 13px;
}

.side-menu :deep(.el-sub-menu__title:hover) {
  background: #2a4035;
  color: #fff;
}

.side-menu :deep(.el-sub-menu.is-active > .el-sub-menu__title) {
  color: #fff;
}

.side-menu :deep(.el-sub-menu__title .el-icon) {
  color: inherit;
  width: 18px;
  margin-right: 10px;
}

.side-menu :deep(.el-sub-menu .el-menu-item) {
  padding-left: 46px !important;
}

.side-menu.el-menu--collapse :deep(.el-sub-menu__title) {
  justify-content: center;
  padding: 0;
}

.side-menu.el-menu--collapse :deep(.el-sub-menu__title .el-icon) {
  margin-right: 0;
}

.side-menu.el-menu--collapse :deep(.el-sub-menu__title .el-sub-menu__icon-arrow) {
  display: none;
}

.side-menu :deep(.el-menu-item:hover) {
  background: #2a4035;
  color: #fff;
}

.side-menu :deep(.el-menu-item.is-active) {
  background: #2a4739;
  color: #fff;
  box-shadow: inset 3px 0 0 #8fc0a7;
}

.side-menu :deep(.el-menu-item .el-icon) {
  color: inherit;
  width: 18px;
  margin-right: 10px;
}

.side-menu.el-menu--collapse :deep(.el-menu-item) {
  justify-content: center;
  padding: 0;
}

.side-menu.el-menu--collapse :deep(.el-menu-item .el-icon) {
  margin-right: 0;
}

.side-foot {
  margin-top: auto;
  padding: 14px 18px 18px;
  border-top: 1px solid #2a4035;
  color: #8fa79a;
  font-size: 11px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.side-foot-sub {
  color: #6f887b;
}

.main-col {
  min-width: 0;
}

.topbar {
  height: 64px;
  background: #fff;
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 24px;
  position: sticky;
  top: 0;
  z-index: 20;
}

.crumb {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  overflow: hidden;
  color: var(--ink-faint);
  font-size: 12.5px;
}

.crumb > * {
  flex-shrink: 0;
}

.crumb-sep {
  color: #a9b6af;
}

.crumb-link {
  border: 0;
  background: none;
  padding: 2px 1px;
  border-radius: 4px;
  color: var(--ink-soft);
  font: inherit;
  cursor: pointer;
}

.crumb-link:hover {
  color: var(--brand);
}

.crumb-link:focus-visible,
.current:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
}

.crumb .current {
  color: var(--ink);
  font-size: 14px;
  font-weight: 650;
  flex: 0 1 auto;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 640px) {
  .crumb > span:first-child,
  .crumb > .crumb-sep:first-of-type {
    display: none;
  }
}

@media (max-width: 480px) {
  .crumb-link,
  .crumb-link + .crumb-sep {
    display: none;
  }
}

.account {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
}

.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--brand-soft);
  border: 1px solid #cfe3d7;
  color: var(--brand-ink);
  font-size: 12.5px;
  font-weight: 700;
}

.account-meta {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
  min-width: 0;
}

.account-meta strong {
  color: var(--ink);
  font-size: 12.5px;
  font-weight: 650;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-meta small {
  color: var(--ink-faint);
  font-size: 10.5px;
}

.logout-button {
  margin-left: 2px;
}

.logout-button :deep(.el-icon) {
  margin-right: 5px;
}

.narrow-note {
  background: var(--warn-soft);
  border-bottom: 1px solid #eeddba;
  color: #75500c;
  padding: 7px 24px;
  font-size: 12px;
}

.main {
  padding: 22px 24px 34px;
  overflow: auto;
}

@media (max-width: 1100px) {
  .topbar {
    padding: 0 18px;
  }

  .main {
    padding: 18px 18px 28px;
  }

  .account-meta {
    display: none;
  }
}

@media (max-width: 900px) {
  .topbar {
    padding: 0 14px;
  }

  .main {
    padding: 16px 14px 26px;
  }

  .narrow-note {
    padding: 7px 14px;
  }
}
</style>
