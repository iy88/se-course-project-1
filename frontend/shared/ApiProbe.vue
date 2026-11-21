<script setup lang="ts">
import { onMounted, ref } from "vue";
import { readHello } from "./api";

const status = ref("正在连接后端…");
const loading = ref(true);

async function checkApi() {
  loading.value = true;
  status.value = "正在连接后端…";
  try {
    const { message } = await readHello();
    if (typeof message !== "string" || !message.trim()) {
      throw new Error("Invalid Hello response");
    }
    status.value = message;
  } catch {
    status.value = "后端连接检查失败。请确认后端已启动后重试。";
  } finally {
    loading.value = false;
  }
}

onMounted(checkApi);
</script>

<template>
  <section class="probe" aria-labelledby="probe-title">
    <h2 id="probe-title">后端连接</h2>
    <code>GET /api/v1/hello</code>
    <p role="status">{{ status }}</p>
    <button type="button" :disabled="loading" @click="checkApi">重新检查</button>
  </section>
</template>
