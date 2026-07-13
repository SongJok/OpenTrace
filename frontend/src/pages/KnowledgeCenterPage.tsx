/**
 * KnowledgeCenterPage - 知识中心
 *
 * 参考Obsidian的知识管理方式：
 * 1. 双向链接系统 [[Note Title]]
 * 2. 知识图谱可视化
 * 3. 渐进式摘要
 * 4. 工作区隔离
 */

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useThemeStore } from '../store/theme'

// 类型定义
interface Note {
  id: string
  title: string
  content: string
  tags: string[]
  outgoingLinks: string[]
  incomingLinks: string[]
  createdAt: string
  updatedAt: string
}

interface GraphNode {
  id: string
  label: string
  x: number
  y: number
  size: number
  color: string
}

interface GraphEdge {
  source: string
  target: string
}

interface KnowledgeGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// 模拟知识图谱数据
const mockGraph: KnowledgeGraph = {
  nodes: [
    { id: '1', label: '产品规划', x: 400, y: 300, size: 30, color: '#4A90D9' },
    { id: '2', label: '技术架构', x: 600, y: 250, size: 25, color: '#E74C3C' },
    { id: '3', label: '用户需求', x: 300, y: 400, size: 20, color: '#2ECC71' },
    { id: '4', label: '竞品分析', x: 500, y: 150, size: 22, color: '#F39C12' },
    { id: '5', label: 'UI设计', x: 200, y: 300, size: 18, color: '#9B59B6' },
    { id: '6', label: '后端API', x: 700, y: 350, size: 20, color: '#E74C3C' },
    { id: '7', label: '数据库设计', x: 650, y: 450, size: 18, color: '#34495E' },
  ],
  edges: [
    { source: '1', target: '2' },
    { source: '1', target: '3' },
    { source: '1', target: '4' },
    { source: '1', target: '5' },
    { source: '2', target: '6' },
    { source: '2', target: '7' },
    { source: '4', target: '1' },
    { source: '3', target: '1' },
  ],
}

interface KnowledgeCenterPageProps {
  onBack?: () => void
}

export default function KnowledgeCenterPage({ onBack }: KnowledgeCenterPageProps) {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { mode } = useThemeStore()
  
  // 状态管理
  const [activeView, setActiveView] = useState<'graph' | 'list' | 'canvas'>('graph')
  const [selectedNote, setSelectedNote] = useState<Note | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [isEditing, setIsEditing] = useState(false)
  const [showLinkSuggestions, setShowLinkSuggestions] = useState(false)
  const [linkTarget, setLinkTarget] = useState('')
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [hoveredNode, setHoveredNode] = useState<string | null>(null)
  
  // 当前编辑的笔记内容
  const [noteContent, setNoteContent] = useState('')
  const [noteTitle, setNoteTitle] = useState('')
  
  // 模拟笔记列表
  const [notes, setNotes] = useState<Note[]>([
    {
      id: '1',
      title: '产品规划',
      content: `# 产品规划

## 目标用户
- 企业数据分析团队
- 产品经理
- 技术团队

## 核心功能
1. [[技术架构]]设计
2. 用户需求调研
3. 竞品分析

## 时间线
- Q1: 原型开发
- Q2: MVP发布
- Q3: 功能完善

#product #planning ^goals`,
      tags: ['product', 'planning'],
      outgoingLinks: ['技术架构', '用户需求', '竞品分析'],
      incomingLinks: [],
      createdAt: '2024-01-15',
      updatedAt: '2024-01-20',
    },
    {
      id: '2',
      title: '技术架构',
      content: `# 技术架构

## 后端技术栈
- Python FastAPI
- PostgreSQL
- Redis
- Docker

## 前端技术栈
- React + TypeScript
- Tailwind CSS

## 部署架构
[[数据库设计]]详细说明...`,
      tags: ['tech', 'architecture'],
      outgoingLinks: ['数据库设计'],
      incomingLinks: ['产品规划'],
      createdAt: '2024-01-16',
      updatedAt: '2024-01-21',
    },
  ])

  // 渲染知识图谱
  useEffect(() => {
    if (activeView !== 'graph' || !canvasRef.current) return

    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // 设置画布大小
    canvas.width = canvas.offsetWidth
    canvas.height = canvas.offsetHeight

    // 绘制函数
    const draw = () => {
      // 清空画布
      ctx.fillStyle = mode === 'dark' ? '#1a1a1a' : '#ffffff'
      ctx.fillRect(0, 0, canvas.width, canvas.height)

      // 绘制边
      ctx.strokeStyle = mode === 'dark' ? '#3a3a3a' : '#e0e0e0'
      ctx.lineWidth = 2
      mockGraph.edges.forEach(edge => {
        const source = mockGraph.nodes.find(n => n.id === edge.source)
        const target = mockGraph.nodes.find(n => n.id === edge.target)
        if (source && target) {
          ctx.beginPath()
          ctx.moveTo(source.x, source.y)
          ctx.lineTo(target.x, target.y)
          ctx.stroke()

          // 绘制箭头
          const angle = Math.atan2(target.y - source.y, target.x - source.x)
          const arrowLength = 10
          const arrowX = target.x - Math.cos(angle) * (target.size + 5)
          const arrowY = target.y - Math.sin(angle) * (target.size + 5)
          
          ctx.beginPath()
          ctx.moveTo(arrowX, arrowY)
          ctx.lineTo(
            arrowX - arrowLength * Math.cos(angle - Math.PI / 6),
            arrowY - arrowLength * Math.sin(angle - Math.PI / 6)
          )
          ctx.moveTo(arrowX, arrowY)
          ctx.lineTo(
            arrowX - arrowLength * Math.cos(angle + Math.PI / 6),
            arrowY - arrowLength * Math.sin(angle + Math.PI / 6)
          )
          ctx.stroke()
        }
      })

      // 绘制节点
      mockGraph.nodes.forEach(node => {
        // 绘制圆形
        ctx.beginPath()
        ctx.arc(node.x, node.y, node.size, 0, Math.PI * 2)
        ctx.fillStyle = node.color
        ctx.fill()
        
        // 高亮hover状态
        if (hoveredNode === node.id) {
          ctx.strokeStyle = '#ffffff'
          ctx.lineWidth = 3
          ctx.stroke()
        }

        // 绘制标签
        ctx.fillStyle = mode === 'dark' ? '#ffffff' : '#1a1a1a'
        ctx.font = '12px sans-serif'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'top'
        ctx.fillText(node.label, node.x, node.y + node.size + 5)
      })
    }

    draw()

    // 添加交互
    const handleMouseMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect()
      const x = e.clientX - rect.left
      const y = e.clientY - rect.top

      // 检查hover
      let found = null
      mockGraph.nodes.forEach(node => {
        const dist = Math.sqrt((x - node.x) ** 2 + (y - node.y) ** 2)
        if (dist < node.size) {
          found = node.id
        }
      })
      setHoveredNode(found)
    }

    const handleClick = (e: MouseEvent) => {
      if (hoveredNode) {
        const note = notes.find(n => n.id === hoveredNode)
        if (note) {
          setSelectedNote(note)
          setNoteContent(note.content)
          setNoteTitle(note.title)
        }
      }
    }

    canvas.addEventListener('mousemove', handleMouseMove)
    canvas.addEventListener('click', handleClick)

    return () => {
      canvas.removeEventListener('mousemove', handleMouseMove)
      canvas.removeEventListener('click', handleClick)
    }
  }, [activeView, mode, hoveredNode, notes])

  // 高亮Wiki链接
  const renderContentWithLinks = (content: string) => {
    const parts = content.split(/(\[\[.*?\]\]|#[a-zA-Z0-9_\-\u4e00-\u9fa5]+|\^[a-zA-Z0-9_-]+)/g)
    
    return parts.map((part, i) => {
      // Wiki链接 [[Title]]
      if (part.startsWith('[[') && part.endsWith(']]')) {
        const linkTitle = part.slice(2, -2)
        return (
          <span
            key={i}
            className="cursor-pointer text-blue-500 hover:underline bg-blue-50 dark:bg-blue-900/30 px-1 rounded"
            onClick={() => handleLinkClick(linkTitle)}
          >
            {linkTitle}
          </span>
        )
      }
      
      // 标签 #tag
      if (part.startsWith('#') && part.length > 1) {
        return (
          <span
            key={i}
            className="text-green-600 dark:text-green-400 cursor-pointer hover:underline"
          >
            {part}
          </span>
        )
      }
      
      // 块引用 ^id
      if (part.startsWith('^')) {
        return (
          <span
            key={i}
            className="text-gray-500 text-sm"
          >
            {part}
          </span>
        )
      }
      
      return <span key={i}>{part}</span>
    })
  }

  const handleLinkClick = (title: string) => {
    const note = notes.find(n => n.title === title)
    if (note) {
      setSelectedNote(note)
      setNoteContent(note.content)
      setNoteTitle(note.title)
    } else {
      // 创建新笔记
      setNoteTitle(title)
      setNoteContent(`# ${title}\n\n`)
      setIsEditing(true)
    }
  }

  const handleSaveNote = () => {
    if (!noteTitle) return
    
    const newNote: Note = {
      id: selectedNote?.id || Date.now().toString(),
      title: noteTitle,
      content: noteContent,
      tags: extractTags(noteContent),
      outgoingLinks: extractLinks(noteContent),
      incomingLinks: selectedNote?.incomingLinks || [],
      createdAt: selectedNote?.createdAt || new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }

    setNotes(prev => {
      const existing = prev.findIndex(n => n.id === newNote.id)
      if (existing >= 0) {
        const updated = [...prev]
        updated[existing] = newNote
        return updated
      }
      return [...prev, newNote]
    })

    setSelectedNote(newNote)
    setIsEditing(false)
  }

  const extractTags = (content: string): string[] => {
    const matches = content.match(/#([a-zA-Z0-9_\-\u4e00-\u9fa5]+)/g) || []
    return matches.map(t => t.slice(1))
  }

  const extractLinks = (content: string): string[] => {
    const matches = content.match(/\[\[([^\]]+)\]\]/g) || []
    return matches.map(l => l.slice(2, -2))
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Ctrl/Cmd + [ 创建链接
    if ((e.metaKey || e.ctrlKey) && e.key === '[') {
      e.preventDefault()
      setShowLinkSuggestions(true)
    }
    
    // Ctrl/Cmd + S 保存
    if ((e.metaKey || e.ctrlKey) && e.key === 's') {
      e.preventDefault()
      handleSaveNote()
    }
  }

  return (
    <div className="h-screen flex flex-col bg-white dark:bg-gray-900">
      {/* 顶部导航栏 */}
      <header className="h-14 border-b border-gray-200 dark:border-gray-700 flex items-center px-4 bg-gray-50 dark:bg-gray-800">
        <button
          onClick={onBack || (() => navigate('/chat'))}
          className="flex items-center text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white mr-4"
        >
          <svg className="w-5 h-5 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          返回
        </button>

        <h1 className="text-lg font-semibold text-gray-900 dark:text-white mr-auto">
          知识中心
        </h1>

        {/* 视图切换 */}
        <div className="flex items-center space-x-2 bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
          <button
            onClick={() => setActiveView('graph')}
            className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
              activeView === 'graph'
                ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow'
                : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
            }`}
          >
            图谱
          </button>
          <button
            onClick={() => setActiveView('list')}
            className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
              activeView === 'list'
                ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow'
                : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
            }`}
          >
            列表
          </button>
          <button
            onClick={() => {
              setActiveView('canvas')
              setSelectedNote(null)
              setNoteTitle('')
              setNoteContent('')
              setIsEditing(true)
            }}
            className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
              activeView === 'canvas'
                ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow'
                : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
            }`}
          >
            新建
          </button>
        </div>
      </header>

      {/* 主体内容 */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧边栏 - 笔记列表 */}
        {activeView === 'list' && (
          <aside className="w-64 border-r border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 flex flex-col">
            {/* 搜索 */}
            <div className="p-4 border-b border-gray-200 dark:border-gray-700">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="搜索笔记..."
                className="w-full px-3 py-2 rounded-lg bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:text-white"
              />
            </div>

            {/* 笔记列表 */}
            <div className="flex-1 overflow-y-auto p-2">
              {notes
                .filter(n => n.title.toLowerCase().includes(searchQuery.toLowerCase()))
                .map(note => (
                  <div
                    key={note.id}
                    onClick={() => {
                      setSelectedNote(note)
                      setNoteContent(note.content)
                      setNoteTitle(note.title)
                      setIsEditing(false)
                    }}
                    className={`p-3 rounded-lg cursor-pointer mb-1 transition-colors ${
                      selectedNote?.id === note.id
                        ? 'bg-blue-100 dark:bg-blue-900/40'
                        : 'hover:bg-gray-200 dark:hover:bg-gray-700'
                    }`}
                  >
                    <h3 className="font-medium text-gray-900 dark:text-white text-sm">
                      {note.title}
                    </h3>
                    <div className="flex items-center mt-1 text-xs text-gray-500 dark:text-gray-400">
                      <span>{note.outgoingLinks.length} 出链</span>
                      <span className="mx-2">•</span>
                      <span>{note.incomingLinks.length} 入链</span>
                    </div>
                    {note.tags.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {note.tags.slice(0, 3).map(tag => (
                          <span
                            key={tag}
                            className="px-1.5 py-0.5 text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded"
                          >
                            #{tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
            </div>
          </aside>
        )}

        {/* 主内容区 */}
        <main className="flex-1 flex overflow-hidden">
          {activeView === 'graph' ? (
            // 图谱视图
            <div className="flex-1 relative">
              <canvas
                ref={canvasRef}
                className="w-full h-full cursor-grab active:cursor-grabbing"
              />
              
              {/* 图例 */}
              <div className="absolute bottom-4 right-4 bg-white dark:bg-gray-800 rounded-lg shadow-lg p-4 text-sm">
                <h4 className="font-medium text-gray-900 dark:text-white mb-2">图例</h4>
                <div className="space-y-1">
                  <div className="flex items-center">
                    <span className="w-3 h-3 rounded-full bg-[#4A90D9] mr-2" />
                    <span className="text-gray-600 dark:text-gray-400">笔记</span>
                  </div>
                  <div className="flex items-center">
                    <span className="w-3 h-3 rounded-full bg-[#E74C3C] mr-2" />
                    <span className="text-gray-600 dark:text-gray-400">概念</span>
                  </div>
                  <div className="flex items-center">
                    <span className="w-3 h-3 rounded-full bg-[#2ECC71] mr-2" />
                    <span className="text-gray-600 dark:text-gray-400">事实</span>
                  </div>
                </div>
                
                <div className="mt-3 text-xs text-gray-500 dark:text-gray-400">
                  <p>节点大小 = 连接数</p>
                  <p>点击节点查看详情</p>
                </div>
              </div>

              {/* 统计信息 */}
              <div className="absolute top-4 left-4 bg-white dark:bg-gray-800 rounded-lg shadow-lg p-4 text-sm">
                <h4 className="font-medium text-gray-900 dark:text-white mb-2">统计</h4>
                <div className="space-y-1 text-gray-600 dark:text-gray-400">
                  <p>笔记: {mockGraph.nodes.length}</p>
                  <p>链接: {mockGraph.edges.length}</p>
                  <p>孤立节点: 0</p>
                </div>
              </div>
            </div>
          ) : (
            // 编辑/阅读视图
            <div className="flex-1 flex">
              {/* 编辑器 */}
              <div className="flex-1 flex flex-col">
                {isEditing ? (
                  <>
                    <input
                      type="text"
                      value={noteTitle}
                      onChange={(e) => setNoteTitle(e.target.value)}
                      placeholder="笔记标题"
                      className="px-6 py-4 text-xl font-semibold border-b border-gray-200 dark:border-gray-700 bg-transparent focus:outline-none dark:text-white"
                    />
                    <textarea
                      value={noteContent}
                      onChange={(e) => setNoteContent(e.target.value)}
                      onKeyDown={handleKeyDown}
                      placeholder="输入内容... 使用 [[笔记名]] 创建链接，#标签 添加标签，^id 引用块"
                      className="flex-1 p-6 resize-none focus:outline-none bg-transparent dark:text-gray-200 font-mono text-sm leading-relaxed"
                    />
                    {/* 工具栏 */}
                    <div className="px-6 py-3 border-t border-gray-200 dark:border-gray-700 flex items-center justify-between bg-gray-50 dark:bg-gray-800">
                      <div className="text-sm text-gray-500 dark:text-gray-400">
                        提示: Ctrl/Cmd + S 保存 | [[ ]] 创建链接
                      </div>
                      <div className="flex space-x-2">
                        <button
                          onClick={() => setIsEditing(false)}
                          className="px-4 py-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                        >
                          取消
                        </button>
                        <button
                          onClick={handleSaveNote}
                          className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
                        >
                          保存
                        </button>
                      </div>
                    </div>
                  </>
                ) : selectedNote ? (
                  <>
                    <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
                      <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
                        {selectedNote.title}
                      </h2>
                      <button
                        onClick={() => setIsEditing(true)}
                        className="px-4 py-2 text-sm text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded"
                      >
                        编辑
                      </button>
                    </div>
                    <div className="flex-1 p-6 overflow-y-auto">
                      <div className="prose dark:prose-invert max-w-none whitespace-pre-wrap">
                        {renderContentWithLinks(selectedNote.content)}
                      </div>
                      
                      {/* 标签 */}
                      {selectedNote.tags.length > 0 && (
                        <div className="mt-8 flex flex-wrap gap-2">
                          {selectedNote.tags.map(tag => (
                            <span
                              key={tag}
                              className="px-2 py-1 text-sm bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded"
                            >
                              #{tag}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </>
                ) : (
                  <div className="flex-1 flex items-center justify-center text-gray-500 dark:text-gray-400">
                    <div className="text-center">
                      <p className="text-lg mb-2">选择一个笔记或创建新笔记</p>
                      <button
                        onClick={() => {
                          setIsEditing(true)
                          setNoteTitle('')
                          setNoteContent('')
                        }}
                        className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
                      >
                        新建笔记
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* 右侧面板 - 关联信息 */}
              {selectedNote && !isEditing && (
                <aside className="w-72 border-l border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 overflow-y-auto">
                  {/* 入链 */}
                  <div className="p-4 border-b border-gray-200 dark:border-gray-700">
                    <h3 className="font-medium text-gray-900 dark:text-white mb-3 flex items-center">
                      <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16l-4-4m0 0l4-4m-4 4h18" />
                      </svg>
                      链接到本页 ({selectedNote.incomingLinks.length})
                    </h3>
                    {selectedNote.incomingLinks.length > 0 ? (
                      <div className="space-y-2">
                        {selectedNote.incomingLinks.map(link => (
                          <div
                            key={link}
                            onClick={() => handleLinkClick(link)}
                            className="p-2 rounded bg-white dark:bg-gray-700 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-600 text-sm"
                          >
                            {link}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-gray-500 dark:text-gray-400">
                        没有笔记链接到这里
                      </p>
                    )}
                  </div>

                  {/* 出链 */}
                  <div className="p-4 border-b border-gray-200 dark:border-gray-700">
                    <h3 className="font-medium text-gray-900 dark:text-white mb-3 flex items-center">
                      <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
                      </svg>
                      本页链接到 ({selectedNote.outgoingLinks.length})
                    </h3>
                    {selectedNote.outgoingLinks.length > 0 ? (
                      <div className="space-y-2">
                        {selectedNote.outgoingLinks.map(link => (
                          <div
                            key={link}
                            onClick={() => handleLinkClick(link)}
                            className="p-2 rounded bg-white dark:bg-gray-700 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-600 text-sm"
                          >
                            {link}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-gray-500 dark:text-gray-400">
                        没有链接到其他笔记
                      </p>
                    )}
                  </div>

                  {/* 元信息 */}
                  <div className="p-4">
                    <h3 className="font-medium text-gray-900 dark:text-white mb-3">元信息</h3>
                    <div className="text-sm text-gray-600 dark:text-gray-400 space-y-2">
                      <p>创建: {new Date(selectedNote.createdAt).toLocaleDateString()}</p>
                      <p>更新: {new Date(selectedNote.updatedAt).toLocaleDateString()}</p>
                      <p>ID: {selectedNote.id.slice(0, 8)}...</p>
                    </div>
                  </div>

                  {/* AI建议 */}
                  <div className="p-4 border-t border-gray-200 dark:border-gray-700">
                    <h3 className="font-medium text-gray-900 dark:text-white mb-3">AI 建议</h3>
                    <div className="space-y-2">
                      <button className="w-full p-2 text-left text-sm bg-purple-50 dark:bg-purple-900/20 text-purple-700 dark:text-purple-400 rounded hover:bg-purple-100 dark:hover:bg-purple-900/30">
                        生成摘要
                      </button>
                      <button className="w-full p-2 text-left text-sm bg-purple-50 dark:bg-purple-900/20 text-purple-700 dark:text-purple-400 rounded hover:bg-purple-100 dark:hover:bg-purple-900/30">
                        发现相关笔记
                      </button>
                      <button className="w-full p-2 text-left text-sm bg-purple-50 dark:bg-purple-900/20 text-purple-700 dark:text-purple-400 rounded hover:bg-purple-100 dark:hover:bg-purple-900/30">
                        提取关键概念
                      </button>
                    </div>
                  </div>
                </aside>
              )}
            </div>
          )}
        </main>
      </div>

      {/* 链接建议弹窗 */}
      {showLinkSuggestions && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-4 w-96">
            <h3 className="font-medium text-gray-900 dark:text-white mb-3">选择要链接的笔记</h3>
            <input
              type="text"
              value={linkTarget}
              onChange={(e) => setLinkTarget(e.target.value)}
              placeholder="输入笔记名或搜索..."
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded mb-3 dark:bg-gray-700 dark:text-white"
              autoFocus
            />
            <div className="max-h-48 overflow-y-auto space-y-1">
              {notes
                .filter(n => n.title.toLowerCase().includes(linkTarget.toLowerCase()))
                .map(note => (
                  <button
                    key={note.id}
                    onClick={() => {
                      setNoteContent(prev => prev + `[[${note.title}]]`)
                      setShowLinkSuggestions(false)
                      setLinkTarget('')
                    }}
                    className="w-full text-left p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded text-sm"
                  >
                    {note.title}
                  </button>
                ))}
            </div>
            <div className="flex justify-end mt-4">
              <button
                onClick={() => {
                  if (linkTarget) {
                    setNoteContent(prev => prev + `[[${linkTarget}]]`)
                  }
                  setShowLinkSuggestions(false)
                  setLinkTarget('')
                }}
                className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 mr-2"
              >
                创建链接
              </button>
              <button
                onClick={() => {
                  setShowLinkSuggestions(false)
                  setLinkTarget('')
                }}
                className="px-4 py-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
