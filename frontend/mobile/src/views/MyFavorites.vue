<template>
  <div class="favorites-page">
    <AppNavBar title="我的收藏" />

    <div class="view">
      <div v-if="session.banned" class="alert alert--warn">
        <AppIcon name="alert" :size="16" />
        <span>封禁期间收藏只读，不能取消收藏；管理沟通仍可用。</span>
      </div>

      <div v-if="error" class="error-banner">
        <AppIcon name="alert" :size="18" />
        <span class="error-banner__text">{{ error }}</span>
        <van-button size="small" plain type="primary" @click="load">重新加载</van-button>
      </div>

      <div v-else-if="favorites.length" class="fav-list">
        <article v-for="f in favorites" :key="f.favorite_id" class="surface fav-card">
          <div class="fav-card__main">
            <span class="fav-card__icon" :class="{ 'fav-card__icon--invalid': !f.valid }">
              <AppIcon :name="f.valid ? 'star' : 'close-circle'" :size="19" />
            </span>
            <div class="fav-card__body">
              <h3 class="fav-card__title" :class="{ 'fav-card__title--invalid': !f.valid }">
                {{ f.valid ? f.title : '商品已失效' }}
              </h3>
              <p class="fav-card__meta">
                <template v-if="f.valid">
                  <span class="price price--sm"><span class="price__symbol">￥</span>{{ fen2yuan(f.price_cents) }}</span>
                </template>
                <template v-else>内容不可见，可取消收藏</template>
              </p>
            </div>
          </div>

          <div class="fav-card__actions">
            <van-button
              v-if="f.valid"
              size="small"
              plain
              type="primary"
              @click="router.push(`/products/${f.product_id}`)"
            >
              查看商品
            </van-button>
            <van-button size="small" plain type="danger" :disabled="session.banned" @click="remove(f)">
              取消收藏
            </van-button>
          </div>
        </article>
      </div>

      <EmptyState
        v-else-if="loaded"
        icon="star"
        title="暂无收藏"
      />
    </div>
  </div>
</template>

<script setup>
import { onActivated, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import EmptyState from '../components/EmptyState.vue'
import http from '../api/http'
import { fen2yuan } from '../api/labels'
import { useSession } from '../stores/session'

const favorites = ref([])
const loaded = ref(false)
const error = ref('')
const session = useSession()
const router = useRouter()

async function load() {
  error.value = ''
  try {
    favorites.value = await http.get('/favorites')
    loaded.value = true
  } catch {
    error.value = '收藏列表加载失败，请稍后重试。'
  }
}

async function remove(f) {
  await http.delete(`/favorites/${f.product_id}`)
  showToast('已取消收藏')
  load()
}

onMounted(load)
onActivated(load)
</script>

<style scoped>
.favorites-page {
  padding-bottom: calc(20px + var(--safe-bottom));
}

.fav-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.fav-card {
  padding: 13px 14px;
}

.fav-card__main {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.fav-card__icon {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: var(--brand-soft);
  color: var(--brand);
}

.fav-card__icon--invalid {
  background: #f1f5f2;
  color: var(--ink-faint);
}

.fav-card__body {
  flex: 1;
  min-width: 0;
}

.fav-card__title {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
  line-height: 1.45;
  word-break: break-word;
}

.fav-card__title--invalid {
  color: var(--ink-soft);
}

.fav-card__meta {
  margin: 4px 0 0;
  color: var(--ink-meta);
  font-size: 12px;
}

.fav-card__actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}
</style>
