<script setup>
defineProps({ title: String })
</script>

<template>
  <div class="app-card">
    <div v-if="title" class="card-header">{{ title }}</div>
    <div class="card-body"><slot /></div>
  </div>
</template>

<style scoped>
.app-card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}
.card-header {
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
  font-size: 14px;
  font-weight: 600;
  color: var(--text-dim);
}
.card-body { padding: 18px; }
</style>