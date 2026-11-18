/**
 * 导航项的唯一来源：侧边栏和命令面板都从这里读。
 *
 * 之前两边各写一份，加一个页面就得改两处，忘一次就出现「侧栏能点、面板搜不到」。
 * `keywords` 是给命令面板用的近义词（拼音首字母 + 英文 + 页面里的功能词），
 * 让输入「shebei / device / 灌溉」也能搜到「总控」。
 */
export type NavItem = {
  to: string
  label: string
  icon: 'board' | 'flow' | 'chat' | 'tasks' | 'report' | 'settings'
  end?: boolean
  /**
   * 侧边栏图标轨的分组：monitor=总览执行 / collab=编排协作 / system=系统。
   * 分组之间画分隔线；命令面板不读这个字段，只读 label/keywords。
   */
  group: 'monitor' | 'collab' | 'system'
  keywords: string[]
}

export const navItems: NavItem[] = [
  { to: '/', label: '总控', icon: 'board', end: true, group: 'monitor', keywords: ['zk', 'dashboard', 'home', '设备', 'device', '土壤', '曲线', '大屏'] },
  { to: '/tasks', label: '任务', icon: 'tasks', group: 'monitor', keywords: ['rw', 'tasks', '任务号', 'task_no', '执行', '队列'] },
  { to: '/report', label: '报告', icon: 'report', group: 'monitor', keywords: ['bg', 'report', '验证', '轮次', '达成率', '日报', 'pdf'] },
  { to: '/canvas', label: '画布', icon: 'flow', group: 'collab', keywords: ['hb', 'canvas', 'workflow', '工作流', '节点', '编排', 'dag', 'run'] },
  { to: '/chat', label: '对话', icon: 'chat', group: 'collab', keywords: ['dh', 'chat', '消息', '剧场', 'agent', '智能体'] },
  { to: '/settings', label: '设置', icon: 'settings', group: 'system', keywords: ['sz', 'settings', '配置', '模型', '知识库', '检索', '智能体', '调度'] },
]
