<template>
  <div class="user-page">
    <AppNavBar title="个人主页" />

    <div v-if="profile" class="view">
      <section class="surface user-hero">
        <span class="avatar-text user-hero__avatar">{{ initialOf(profile.display_name) }}</span>
        <div class="user-hero__main">
          <h1>{{ profile.display_name }}</h1>
          <p>在售 {{ profile.products.length }} 件闲置</p>
        </div>
        <span v-if="profile.is_self" class="pill pill--brand">本人</span>
      </section>

      <section class="surface products-section">
        <header class="products-section__head">
          <h2>在售商品</h2>
          <span>{{ profile.products.length }} 件</span>
        </header>

        <div v-if="profile.products.length" class="product-links">
          <router-link v-for="p in profile.products" :key="p.id" :to="`/products/${p.id}`" class="product-link">
            <span class="thumb">
              <van-image v-if="p.image_url" width="100%" height="100%" fit="cover" :src="p.image_url">
                <template #error>
                  <span class="thumb-placeholder"><AppIcon name="image" :size="20" /></span>
                </template>
              </van-image>
              <span v-else class="thumb-placeholder"><AppIcon name="image" :size="20" /></span>
            </span>
            <span class="product-link__main">
              <span class="product-link__title">{{ p.title }}</span>
              <span class="price price--sm"><span class="price__symbol">￥</span>{{ fen2yuan(p.price_cents) }}</span>
            </span>
            <AppIcon name="chevron-right" :size="16" class="product-link__arrow" />
          </router-link>
        </div>

        <EmptyState v-else icon="box" title="暂无在售商品" />
      </section>

      <div v-if="!profile.is_self" class="chat-cta">
        <van-button type="primary" block @click="startChat">发起私聊</van-button>
      </div>
    </div>

    <div v-else-if="error" class="view">
      <div class="error-banner">
        <AppIcon name="alert" :size="18" />
        <span class="error-banner__text">{{ error }}</span>
        <van-button size="small" plain type="primary" @click="load">重新加载</van-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import EmptyState from '../components/EmptyState.vue'
import http from '../api/http'
import { fen2yuan } from '../api/labels'

const route = useRoute()
const router = useRouter()
const profile = ref(null)
const error = ref('')

function initialOf(name) {
  return name ? Array.from(name)[0] : '用'
}

async function startChat() {
  const data = await http.post('/conversations/normal', { peer_user_id: Number(route.params.id) })
  showToast('会话已就绪')
  router.push(`/conversations/${data.id}`)
}

async function load() {
  error.value = ''
  try {
    profile.value = await http.get(`/users/${route.params.id}/profile`)
  } catch {
    error.value = '用户主页加载失败，请稍后重试。'
  }
}

onMounted(load)
</script>

<style scoped>
.user-page {
  padding-bottom: calc(20px + var(--safe-bottom));
}

.user-hero {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
}

.user-hero__avatar {
  width: 52px;
  height: 52px;
  font-size: 20px;
}

.user-hero__main {
  flex: 1;
  min-width: 0;
}

.user-hero__main h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.35;
  word-break: break-word;
}

.user-hero__main p {
  margin: 2px 0 0;
  color: var(--ink-meta);
  font-size: 12px;
}

.products-section {
  margin-top: 12px;
  overflow: hidden;
}

.products-section__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 13px 16px 11px;
  border-bottom: 1px solid var(--line);
}

.products-section__head h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
}

.products-section__head span {
  color: var(--ink-meta);
  font-size: 11.5px;
}

.product-links {
  padding: 2px 0;
}

.product-link {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  color: var(--ink);
  text-decoration: none;
}

.product-link + .product-link {
  border-top: 1px solid var(--line);
}

.product-link:active {
  background: #f4f8f5;
}

.product-link .thumb {
  width: 48px;
  height: 48px;
  border-radius: 9px;
}

.product-link__main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.product-link__title {
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.product-link__arrow {
  flex: 0 0 auto;
  color: var(--ink-faint);
}

.chat-cta {
  margin-top: 16px;
}

.chat-cta :deep(.van-button) {
  height: 44px;
}
</style>
