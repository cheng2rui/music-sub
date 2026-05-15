<script setup>
defineProps({
  color: { type: String, default: 'dim' }
})
</script>

<template>
  <span class="badge" :class="`badge-${color}`"><slot /></span>
</template>

<style scoped>
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.badge-green { background: rgba(29,185,84,0.15); color: var(--success); }
.badge-blue { background: rgba(0,102,204,0.15); color: #0099ff; }
.badge-orange { background: rgba(230,167,0,0.15); color: var(--warning); }
.badge-red { background: rgba(233,20,41,0.15); color: var(--danger); }
.badge-dim { background: var(--surface-hover); color: var(--text-dim); }
</style>