# Error Recovery Dialog Component

Vue 3 组件，用于展示 SQL 执行失败时的用户恢复选项。

## 功能特性

- 🎯 **智能建议**：根据错误类型自动推荐操作（手动修正/联系管理员/稍后重试）
- 📋 **一键复制**：Trace ID 快速复制，便于技术支持
- 📜 **重试历史**：折叠展示多次重试的错误堆栈
- 💻 **SQL 预览**：可选显示原始查询语句，辅助手动修正
- ♿ **无障碍支持**：ARIA 标签 + 键盘导航

## 使用示例

```vue
<template>
  <RecoveryDialog
    v-if="showRecovery"
    :recovery-context="errorContext"
    :show-sql-preview="true"
    @close="showRecovery = false"
    @action="handleRecoveryAction"
    @copy-trace="onTraceCopied"
  />
</template>

<script setup lang="ts">
import { ref } from 'vue'
import RecoveryDialog, { type RecoveryContext } from './ErrorRecovery/RecoveryDialog.vue'

const showRecovery = ref(false)
const errorContext = ref<RecoveryContext | null>(null)

// 从 API 错误响应中提取 recovery_context
const handleApiError = async (error: any) => {
  if (error.response?.data?.recovery_context) {
    errorContext.value = error.response.data.recovery_context
    showRecovery.value = true
  }
}

// 处理用户选择的恢复操作
const handleRecoveryAction = (suggestion: RecoverySuggestion) => {
  switch (suggestion.action) {
    case 'manual_fix':
      // 打开 SQL 编辑器，预填原始查询
      openSqlEditor(errorContext.value?.last_sql)
      break
    case 'contact_admin':
      // 打开支持工单，附带 trace_id
      openSupportTicket({
        traceId: errorContext.value?.trace_id,
        error: errorContext.value?.error_history?.[0],
      })
      break
    case 'retry_later':
      // 设置延迟重试
      scheduleRetry(5000)
      break
  }
}

const onTraceCopied = (traceId: string) => {
  // 可选：显示复制成功 toast
  showToast('Trace ID 已复制到剪贴板')
}
</script>
```

## 后端集成

后端 `QueryExecutor` 在最终失败时会返回结构化错误：

```python
# Python 后端示例
try:
    rows, sql, warnings = await executor.run_with_retry(...)
except SQLValidationError as exc:
    # exc.recovery_context 包含前端需要的结构化数据
    return JSONResponse(
        status_code=400,
        content={
            "error": str(exc),
            "recovery_context": exc.recovery_context,  # ← 前端直接使用
        }
    )
```

`recovery_context` 数据结构：

```typescript
interface RecoveryContext {
  trace_id: string              // 唯一追踪 ID
  error_history: string[]       // 按时间排序的错误列表
  suggestions: Array<{          // 用户可操作的建议
    action: 'manual_fix' | 'contact_admin' | 'retry_later'
    label: string               // 按钮文案
    description: string         // 简短说明
    hint?: string               // 可选的额外提示
  }>
  attempt_count: number         // 重试次数
  last_sql?: string             // 最后一次尝试的 SQL
}
```

## 样式定制

组件使用 CSS 变量支持主题定制：

```css
:root {
  --recovery-border-color: #e5e7eb;
  --recovery-primary: #3b82f6;
  --recovery-warning-bg: #fef3c7;
  --recovery-warning-text: #92400e;
}
```

## 测试

```bash
# 运行组件单元测试
npm test -- RecoveryDialog

# 运行 E2E 测试（需要 Playwright）
npx playwright test recovery-flow
```
