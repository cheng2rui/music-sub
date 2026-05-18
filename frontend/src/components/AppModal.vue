<script setup>
import { onMounted, onUnmounted } from 'vue'

const props = defineProps({
  title: String
})

const emit = defineEmits(['close'])

function handleKeydown(e) {
  if (e.key === 'Escape') emit('close')
}

onMounted(() => document.addEventListener('keydown', handleKeydown))
onUnmounted(() => document.removeEventListener('keydown', handleKeydown))
</script>

<template>
  <Teleport to="body">
    <div class="modal-overlay" @click.self="$emit('close')">
      <div class="modal-box">
        <div class="modal-header">
          <h3 v-if="title">{{ title }}</h3>
          <button class="modal-close" @click="$emit('close')">✕</button>
        </div>
        <div class="modal-body">
          <slot />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0;
  background: var(--overlay-bg);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
  padding: 16px;
}
.modal-box {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-soft);
  min-width: 360px;
  max-width: 90vw;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.modal-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}
.modal-header h3 { font-size: 16px; font-weight: 600; }
.modal-close {
  background: none; border: none;
  color: var(--text-muted); cursor: pointer;
  font-size: 16px; padding: 4px;
}
.modal-close:hover { color: var(--text); }
.modal-body { padding: 20px; overflow-y: auto; }

@media (max-width: 768px) {
  .modal-overlay {
    align-items: flex-end;
    padding: 12px max(10px, env(safe-area-inset-right)) calc(84px + env(safe-area-inset-bottom)) max(10px, env(safe-area-inset-left));
  }
  .modal-box {
    width: 100%;
    min-width: 0;
    max-width: 100%;
    max-height: min(82vh, 720px);
    border-radius: 20px;
  }
  .modal-header { padding: 14px 16px; }
  .modal-body { padding: 14px; }
}
</style>