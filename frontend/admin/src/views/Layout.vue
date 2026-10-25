<template>
  <el-container style="height: 100%">
    <el-aside width="220px" class="aside">
      <div class="brand">🛒 校园二手 · 管理端</div>
      <el-menu :default-active="$route.path" router background-color="#001529" text-color="#c8c9cc" active-text-color="#fff">
        <el-menu-item index="/cases">📋 待处理池</el-menu-item>
        <el-menu-item index="/reports">🚩 举报核查</el-menu-item>
        <el-menu-item index="/products">📦 商品管理</el-menu-item>
        <el-menu-item index="/trades">🤝 交易处置</el-menu-item>
        <el-menu-item index="/users">👤 账户管理</el-menu-item>
        <el-menu-item index="/categories">🏷️ 分类标签</el-menu-item>
        <el-menu-item index="/prohibited">🚫 禁发范围</el-menu-item>
        <el-menu-item index="/stats">📊 数据统计</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <span>{{ $route.meta.title || '管理端' }}</span>
        <div>
          <span style="margin-right: 12px">{{ adminName }}</span>
          <el-button link type="danger" @click="logout">退出</el-button>
        </div>
      </el-header>
      <el-main><router-view /></el-main>
    </el-container>
    <div v-if="isNarrow" class="narrow-tip">管理端面向桌面浏览器使用，请在电脑端打开</div>
  </el-container>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const adminName = ref(localStorage.getItem('admin_name') || '管理员')
const isNarrow = ref(false)

onMounted(() => {
  const check = () => (isNarrow.value = window.innerWidth < 900)
  check()
  window.addEventListener('resize', check)
})

function logout() {
  localStorage.removeItem('admin_token')
  localStorage.removeItem('admin_name')
  router.push('/login')
}
</script>

<style scoped>
.aside {
  background: #001529;
}
.brand {
  color: #fff;
  font-weight: 600;
  padding: 18px 16px;
  font-size: 15px;
}
.header {
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e4e7ed;
  font-weight: 600;
}
.narrow-tip {
  position: fixed;
  inset: 0;
  background: rgba(245, 247, 250, 0.97);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #606266;
  z-index: 999;
  padding: 24px;
  text-align: center;
}
</style>
