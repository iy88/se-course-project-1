<template>
  <div class="login-shell">
    <section class="login-intro">
      <div class="intro-inner">
        <div class="login-brand">
          <span class="brand-mark"><AppIcon name="brand" :size="22" /></span>
          <span>
            <strong>校园二手交易平台</strong>
            <small>管理端</small>
          </span>
        </div>

        <p class="intro-eyebrow">ADMIN CONSOLE</p>
        <h1>审核、处置与留痕，在同一个工作台完成</h1>
        <p class="intro-lead">
          面向平台管理员的内容审核与交易处置控制台。登录后可认领事项、核查举报、冻结交易，并维护账户与分类。
        </p>

        <ul class="intro-points">
          <li>
            <span class="point-icon"><AppIcon name="cases" :size="17" /></span>
            <span><strong>事项认领与沟通</strong><small>在共享池认领后查看非公开内容并留痕回复</small></span>
          </li>
          <li>
            <span class="point-icon"><AppIcon name="reports" :size="17" /></span>
            <span><strong>举报核查与公开结果</strong><small>在事项处理中提交核查结论、匿名公开摘要与处置动作</small></span>
          </li>
          <li>
            <span class="point-icon"><AppIcon name="trades" :size="17" /></span>
            <span><strong>交易冻结与状态调整</strong><small>在事项处理中基于认领事项操作，动作记录依据并通知双方</small></span>
          </li>
          <li>
            <span class="point-icon"><AppIcon name="users" :size="17" /></span>
            <span><strong>账户封禁与分类维护</strong><small>封禁、解除封禁及公共标签、禁发范围维护</small></span>
          </li>
        </ul>

        <p class="intro-foot">
          <AppIcon name="shield" :size="15" />
          仅平台管理员可登录；其他用户请使用移动端。
        </p>
      </div>
    </section>

    <section class="login-panel">
      <div class="login-card">
        <header class="login-head">
          <span class="kicker">管理端登录</span>
          <h2>管理员账户</h2>
          <p>使用平台管理员账户登录。</p>
        </header>

        <el-form :model="form" label-position="top" @keyup.enter="submit">
          <el-form-item label="邮箱">
            <el-input
              v-model="form.email"
              type="email"
              autocomplete="username"
              placeholder="admin@campus.edu"
              size="large"
            />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="form.password"
              type="password"
              autocomplete="current-password"
              show-password
              size="large"
            />
          </el-form-item>
          <el-button type="primary" size="large" class="login-submit" :loading="loading" @click="submit">
            登录管理端
          </el-button>
        </el-form>

        <p class="login-assist">
          非管理员账户无法登录管理端。
        </p>
      </div>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '../api/http'
import { useSession } from '../stores/session'
import AppIcon from '../components/AppIcon.vue'

const router = useRouter()
const session = useSession()
const form = reactive({ email: '', password: '' })
const loading = ref(false)

async function submit() {
  if (!form.email || !form.password) return ElMessage.warning('请输入邮箱和密码')
  loading.value = true
  try {
    const data = await http.post('/auth/login', form)
    if (data.user.role !== 'admin') {
      ElMessage.error('该账户不是平台管理员')
      return
    }
    session.setSession(data.access_token, data.user)
    router.push('/cases')
  } catch {
    // 失败反馈由 http 响应拦截器统一提示，登录态与管理员校验保持不变。
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-shell {
  min-height: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1.04fr) minmax(420px, 0.96fr);
  background: var(--bg);
}

.login-intro {
  background: #1e2f28;
  color: #e8f0eb;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 56px;
  border-right: 1px solid #2a4035;
}

.intro-inner {
  width: 100%;
  max-width: 560px;
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 11px;
  margin-bottom: 44px;
}

.brand-mark {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: var(--brand);
  color: #fff;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.16);
}

.login-brand strong {
  display: block;
  color: #fff;
  font-size: 14px;
  font-weight: 650;
  letter-spacing: 0.02em;
}

.login-brand small {
  display: block;
  color: #9fb5a9;
  font-size: 10.5px;
  letter-spacing: 0.18em;
}

.intro-eyebrow {
  color: #8fc0a7;
  font-size: 11px;
  letter-spacing: 0.18em;
  font-weight: 600;
  margin-bottom: 10px;
}

.login-intro h1 {
  color: #fff;
  font-size: 28px;
  max-width: 560px;
  line-height: 1.34;
  letter-spacing: -0.01em;
  margin-bottom: 14px;
}

.intro-lead {
  color: #b9c9c0;
  font-size: 13.5px;
  max-width: 48ch;
  margin-bottom: 28px;
}

.intro-points {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.intro-points li {
  display: flex;
  align-items: flex-start;
  gap: 11px;
}

.point-icon {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: #2a4035;
  border: 1px solid #3a5346;
  color: #9fc7b2;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
}

.intro-points strong {
  display: block;
  color: #eef5f1;
  font-size: 12.5px;
  font-weight: 600;
}

.intro-points small {
  display: block;
  color: #93a89d;
  font-size: 11.5px;
  line-height: 1.5;
}

.intro-foot {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #8fa79a;
  font-size: 11.5px;
  border-top: 1px solid #2a4035;
  margin-top: 32px;
  padding-top: 16px;
}

.login-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 28px;
}

.login-card {
  width: 100%;
  max-width: 404px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 30px 30px 24px;
}

.login-head {
  margin-bottom: 22px;
}

.kicker {
  color: var(--brand);
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0.1em;
}

.login-head h2 {
  color: var(--ink);
  font-size: 22px;
  margin-top: 4px;
}

.login-head p {
  color: var(--ink-soft);
  font-size: 12.5px;
  margin-top: 5px;
}

.login-submit {
  width: 100%;
  margin-top: 4px;
}

.login-assist {
  color: var(--ink-faint);
  font-size: 11.5px;
  line-height: 1.6;
  border-top: 1px solid var(--line);
  margin-top: 22px;
  padding-top: 14px;
}

@media (max-width: 980px) {
  .login-shell {
    grid-template-columns: minmax(0, 1fr);
  }

  .login-intro {
    padding: 32px 26px;
    border-right: 0;
    border-bottom: 1px solid #2a4035;
  }

  .login-brand {
    margin-bottom: 24px;
  }

  .login-intro h1 {
    font-size: 24px;
  }

  .intro-points {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }

  .login-panel {
    padding: 28px 18px 40px;
  }
}

@media (max-width: 600px) {
  .intro-points {
    grid-template-columns: minmax(0, 1fr);
  }

  .login-card {
    padding: 24px 20px 20px;
  }
}
</style>
