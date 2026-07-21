<template>
  <div class="recovery-dialog-overlay" @click.self="onClose">
    <div class="recovery-dialog" role="dialog" aria-modal="true">
      <!-- Header -->
      <div class="recovery-header">
        <h3>⚠️ 查询执行失败</h3>
        <button class="close-btn" @click="onClose" aria-label="关闭">✕</button>
      </div>

      <!-- Error Summary -->
      <div class="error-summary">
        <p class="error-message">{{ lastError }}</p>
        <div v-if="recoveryContext.trace_id" class="trace-id">
          <span class="label">Trace ID:</span>
          <code>{{ recoveryContext.trace_id }}</code>
          <button class="copy-btn" @click="copyTraceId" title="复制">📋</button>
        </div>
      </div>

      <!-- Error History (collapsible) -->
      <details v-if="recoveryContext.error_history?.length > 1" class="error-history">
        <summary>查看重试历史 ({{ recoveryContext.attempt_count }} 次)</summary>
        <ul class="history-list">
          <li v-for="(err, idx) in recoveryContext.error_history" :key="idx">
            <span class="attempt-num">#{{ idx + 1 }}</span>
            <span class="err-text">{{ truncateError(err) }}</span>
          </li>
        </ul>
      </details>

      <!-- Recovery Suggestions -->
      <div class="suggestions">
        <h4>建议操作</h4>
        <div class="suggestion-cards">
          <div
            v-for="suggestion in recoveryContext.suggestions"
            :key="suggestion.action"
            class="suggestion-card"
            :class="suggestion.action"
            @click="handleSuggestion(suggestion)"
            role="button"
            tabindex="0"
            @keyup.enter="handleSuggestion(suggestion)"
          >
            <div class="suggestion-icon">{{ getIcon(suggestion.action) }}</div>
            <div class="suggestion-content">
              <strong>{{ suggestion.label }}</strong>
              <p class="description">{{ suggestion.description }}</p>
              <p v-if="suggestion.hint" class="hint">{{ suggestion.hint }}</p>
            </div>
          </div>
        </div>
      </div>

      <!-- SQL Preview (optional) -->
      <div v-if="showSqlPreview && recoveryContext.last_sql" class="sql-preview">
        <details>
          <summary>查看原始 SQL</summary>
          <pre class="sql-code"><code>{{ recoveryContext.last_sql }}</code></pre>
        </details>
      </div>

      <!-- Footer Actions -->
      <div class="recovery-footer">
        <button class="btn-secondary" @click="onClose">取消</button>
        <button 
          v-if="primaryAction"
          class="btn-primary"
          @click="handlePrimaryAction"
        >
          {{ primaryAction.label }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useClipboard } from '@vueuse/core'

export interface RecoverySuggestion {
  action: 'manual_fix' | 'contact_admin' | 'retry_later' | string
  label: string
  description: string
  hint?: string
}

export interface RecoveryContext {
  trace_id: string
  error_history: string[]
  suggestions: RecoverySuggestion[]
  attempt_count: number
  last_sql?: string
}

const props = defineProps<{
  recoveryContext: RecoveryContext
  showSqlPreview?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'action', action: RecoverySuggestion): void
  (e: 'copy-trace', traceId: string): void
}>()

const { copy: copyToClipboard, copied } = useClipboard()

const lastError = computed(() => 
  props.recoveryContext.error_history?.[0] || '未知错误'
)

const primaryAction = computed(() => 
  props.recoveryContext.suggestions?.[0]
)

const onClose = () => emit('close')

const copyTraceId = async () => {
  if (props.recoveryContext.trace_id) {
    await copyToClipboard(props.recoveryContext.trace_id)
    emit('copy-trace', props.recoveryContext.trace_id)
  }
}

const truncateError = (err: string, maxLen = 120) => 
  err.length > maxLen ? err.slice(0, maxLen) + '...' : err

const getIcon = (action: string): string => {
  const icons: Record<string, string> = {
    manual_fix: '✏️',
    contact_admin: '👨‍💻',
    retry_later: '🔄',
  }
  return icons[action] || '💡'
}

const handleSuggestion = (suggestion: RecoverySuggestion) => {
  emit('action', suggestion)
  if (suggestion.action !== 'manual_fix') {
    onClose()
  }
}

const handlePrimaryAction = () => {
  if (primaryAction.value) {
    handleSuggestion(primaryAction.value)
  }
}
</script>

<style scoped>
.recovery-dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 1rem;
}

.recovery-dialog {
  background: #fff;
  border-radius: 12px;
  max-width: 560px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
}

.recovery-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid #eee;
}

.recovery-header h3 {
  margin: 0;
  font-size: 1.1rem;
  color: #d97706;
}

.close-btn {
  background: none;
  border: none;
  font-size: 1.25rem;
  cursor: pointer;
  padding: 0.25rem;
  color: #666;
}

.close-btn:hover {
  color: #333;
}

.error-summary {
  padding: 1rem 1.25rem;
  background: #fef3c7;
  border-bottom: 1px solid #fcd34d;
}

.error-message {
  margin: 0 0 0.5rem 0;
  font-size: 0.95rem;
  color: #92400e;
  line-height: 1.4;
}

.trace-id {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  color: #666;
}

.trace-id code {
  background: #f3f4f6;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  font-family: monospace;
}

.copy-btn {
  background: none;
  border: none;
  cursor: pointer;
  padding: 0.1rem;
  font-size: 0.9rem;
}

.error-history {
  padding: 0.75rem 1.25rem;
  border-bottom: 1px solid #eee;
  font-size: 0.9rem;
}

.error-history summary {
  cursor: pointer;
  color: #666;
  margin-bottom: 0.5rem;
}

.history-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.history-list li {
  display: flex;
  gap: 0.5rem;
  padding: 0.25rem 0;
  color: #555;
}

.attempt-num {
  font-weight: 600;
  color: #999;
  min-width: 2rem;
}

.err-text {
  font-family: monospace;
  font-size: 0.85rem;
  color: #dc2626;
}

.suggestions {
  padding: 1rem 1.25rem;
}

.suggestions h4 {
  margin: 0 0 0.75rem 0;
  font-size: 1rem;
  color: #333;
}

.suggestion-cards {
  display: grid;
  gap: 0.75rem;
}

.suggestion-card {
  display: flex;
  gap: 0.75rem;
  padding: 0.875rem;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s ease;
  background: #fff;
}

.suggestion-card:hover {
  border-color: #3b82f6;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.1);
}

.suggestion-card:focus {
  outline: 2px solid #3b82f6;
  outline-offset: 2px;
}

.suggestion-icon {
  font-size: 1.25rem;
  flex-shrink: 0;
}

.suggestion-content {
  flex: 1;
}

.suggestion-content strong {
  display: block;
  margin-bottom: 0.25rem;
  color: #1f2937;
}

.description {
  margin: 0 0 0.25rem 0;
  font-size: 0.9rem;
  color: #4b5563;
}

.hint {
  margin: 0;
  font-size: 0.85rem;
  color: #6b7280;
  font-style: italic;
}

.sql-preview {
  padding: 0 1.25rem 1rem;
}

.sql-preview details {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 0.75rem;
  background: #f9fafb;
}

.sql-preview summary {
  cursor: pointer;
  color: #374151;
  font-size: 0.9rem;
}

.sql-code {
  margin: 0.75rem 0 0 0;
  padding: 0.75rem;
  background: #1f2937;
  color: #e5e7eb;
  border-radius: 4px;
  font-size: 0.85rem;
  overflow-x: auto;
  max-height: 200px;
}

.sql-code code {
  white-space: pre-wrap;
  word-break: break-all;
}

.recovery-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-top: 1px solid #eee;
  background: #f9fafb;
  border-radius: 0 0 12px 12px;
}

.btn-secondary,
.btn-primary {
  padding: 0.5rem 1.25rem;
  border-radius: 6px;
  font-size: 0.95rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-secondary {
  background: #fff;
  border: 1px solid #d1d5db;
  color: #374151;
}

.btn-secondary:hover {
  background: #f3f4f6;
}

.btn-primary {
  background: #3b82f6;
  border: none;
  color: #fff;
}

.btn-primary:hover {
  background: #2563eb;
}
</style>
