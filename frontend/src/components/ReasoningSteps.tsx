/**
 * ReasoningSteps - 推理步骤可视化组件
 *
 * 参考ChatGPT的推理展示效果，实时显示AI的思考过程
 */
import React from 'react';

interface ToolCall {
  tool_name: string;
  parameters: Record<string, unknown>;
  result_preview?: string;
  execution_time_ms: number;
}

interface ReasoningStepData {
  id: string;
  type: string;
  title: string;
  description: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed';
  progress: number;
  started_at?: string;
  completed_at?: string;
  tool_calls: ToolCall[];
  metadata?: Record<string, unknown>;
}

interface ReasoningStepsProps {
  steps: ReasoningStepData[];
  currentStepId?: string;
  isComplete?: boolean;
}

const stepTypeConfig: Record<string, { icon: string; color: string }> = {
  analysis: { icon: '🔍', color: 'blue' },
  planning: { icon: '📋', color: 'purple' },
  retrieving: { icon: '📚', color: 'indigo' },
  executing: { icon: '⚙️', color: 'orange' },
  reflecting: { icon: '🤔', color: 'pink' },
  synthesizing: { icon: '✨', color: 'green' },
  complete: { icon: '✅', color: 'green' },
};

const getStatusIcon = (status: string) => {
  switch (status) {
    case 'pending':
      return '○';
    case 'in_progress':
      return (
        <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      );
    case 'completed':
      return '✓';
    case 'failed':
      return '✗';
    default:
      return '○';
  }
};

const getStatusColor = (status: string) => {
  switch (status) {
    case 'pending':
      return 'text-gray-400';
    case 'in_progress':
      return 'text-blue-500';
    case 'completed':
      return 'text-green-500';
    case 'failed':
      return 'text-red-500';
    default:
      return 'text-gray-400';
  }
};

export default function ReasoningSteps({ steps, currentStepId, isComplete }: ReasoningStepsProps) {
  if (!steps || steps.length === 0) {
    return null;
  }

  return (
    <div className="bg-gray-50 dark:bg-gray-800/50 rounded-lg p-4 mb-4">
      {/* 头部 */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 flex items-center">
          <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
          思考过程
        </h3>
        {isComplete && (
          <span className="text-xs text-green-600 dark:text-green-400 flex items-center">
            <svg className="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            已完成
          </span>
        )}
      </div>

      {/* 步骤列表 */}
      <div className="space-y-2">
        {steps.map((step, index) => {
          const config = stepTypeConfig[step.type] || { icon: '•', color: 'gray' };
          const isCurrent = step.id === currentStepId;
          const isActive = step.status === 'in_progress' || step.status === 'completed';
          const showDetails = step.status === 'in_progress' || step.status === 'completed';

          return (
            <div
              key={step.id}
              className={`relative pl-6 ${isCurrent ? 'opacity-100' : isActive ? 'opacity-80' : 'opacity-50'}`}
            >
              {/* 连接线 */}
              {index < steps.length - 1 && (
                <div className="absolute left-2 top-6 w-0.5 h-full bg-gray-200 dark:bg-gray-700 -translate-x-1/2" />
              )}

              {/* 状态圆点 */}
              <div
                className={`absolute left-0 top-1 w-4 h-4 rounded-full flex items-center justify-center text-xs ${
                  step.status === 'completed'
                    ? 'bg-green-100 text-green-600 dark:bg-green-900/30 dark:text-green-400'
                    : step.status === 'in_progress'
                    ? 'bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400'
                    : step.status === 'failed'
                    ? 'bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400'
                    : 'bg-gray-100 text-gray-400 dark:bg-gray-700'
                }`}
              >
                {getStatusIcon(step.status)}
              </div>

              {/* 步骤内容 */}
              <div
                className={`p-3 rounded-lg transition-all ${
                  isCurrent
                    ? 'bg-white dark:bg-gray-700 shadow-sm border border-blue-200 dark:border-blue-800'
                    : 'bg-transparent'
                }`}
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-start">
                    <span className="text-base mr-2">{config.icon}</span>
                    <div>
                      <p className={`text-sm font-medium ${isCurrent ? 'text-gray-900 dark:text-white' : 'text-gray-700 dark:text-gray-300'}`}>
                        {step.title}
                      </p>
                      {step.description && (
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{step.description}</p>
                      )}
                    </div>
                  </div>
                  <span className={`text-xs ${getStatusColor(step.status)}`}>
                    {step.status === 'in_progress' && `${Math.round(step.progress * 100)}%`}
                  </span>
                </div>

                {/* 进度条 */}
                {step.status === 'in_progress' && (
                  <div className="mt-2 h-1 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-blue-500 rounded-full transition-all duration-300"
                      style={{ width: `${step.progress * 100}%` }}
                    />
                  </div>
                )}

                {/* 工具调用详情 */}
                {showDetails && step.tool_calls && step.tool_calls.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {step.tool_calls.map((tc, idx) => (
                      <div
                        key={idx}
                        className="flex items-center text-xs text-gray-500 dark:text-gray-400 pl-4"
                      >
                        <svg className="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                        </svg>
                        <span className="font-mono">{tc.tool_name}</span>
                        {tc.execution_time_ms > 0 && (
                          <span className="ml-2 text-gray-400">({tc.execution_time_ms}ms)</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {/* 错误信息 */}
                {step.status === 'failed' && step.metadata?.error && (
                  <div className="mt-2 p-2 bg-red-50 dark:bg-red-900/20 rounded text-xs text-red-600 dark:text-red-400">
                    {String(step.metadata.error)}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* 摘要统计 */}
      {isComplete && (
        <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
            <span>
              {steps.filter(s => s.status === 'completed').length} / {steps.length} 步骤完成
            </span>
            <span>
              {steps.reduce((acc, s) => acc + s.tool_calls.length, 0)} 个工具调用
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
