<template>
  <div class="stack stack--loose">
    <h1 class="not-found__title">页面不存在</h1>
    <p class="muted">该地址没有对应的页面，或者你当前无权访问。</p>
    <div class="inline">
      <RouterLink to="/" class="btn btn--primary">回到逛逛</RouterLink>
      <RouterLink to="/me" class="btn btn--ghost">我的</RouterLink>
    </div>
  </div>
</template>

<style scoped>
.not-found__title {
  font-size: 1.375rem;
}
</style>
