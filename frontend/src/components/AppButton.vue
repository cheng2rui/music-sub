<script setup>
defineProps({
  variant: { type: String, default: 'primary' },
  size: { type: String, default: 'md' },
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false }
})
</script>

<template>
  <button
    class="app-btn"
    :class="[`btn-${variant}`, `btn-${size}`, { 'btn-loading': loading }]"
    :disabled="disabled || loading"
  >
    <span v-if="loading" class="spinner"></span>
    <slot />
  </button>
</template>

<style scoped>
.app-btn {
  display: inline-flex; align-items: center; gap: 6px;
  border: none; border-radius: var(--radius-md);
  font-size: 14px; font-weight: 600;
  cursor: pointer; transition: all 0.15s;
}
.app-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* Sizes */
.btn-sm { padding: 6px 12px; font-size: 12px; }
.btn-md { padding: 8px 18px; font-size: 14px; }

/* Variants */
.btn-primary { background: var(--accent); color: #000; }
.btn-primary:hover:not(:disabled) { background: var(--accent-hover); }
.btn-success { background: var(--success); color: #000; }
.btn-danger { background: var(--danger); color: #fff; }
.btn-ghost { background: transparent; color: var(--text-dim); border: 1px solid var(--border); }
.btn-ghost:hover:not(:disabled) { background: var(--surface); color: var(--text); }

/* Loading */
.btn-loading { position: relative; }
.spinner {
  width: 14px; height: 14px;
  border: 2px solid transparent;
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>