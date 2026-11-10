import { useState } from 'react'
import { GardenPhoto } from '../components/GardenPhoto'
import { taskColumns } from '../data/snapshot'

const filters = ['全部', '执行中', '成功', '重试', '熔断']

export function TasksPage() {
  const [filter, setFilter] = useState(filters[0])

  return (
    <div className="page-enter mx-auto flex w-full max-w-[1360px] flex-col gap-4">
      <header>
        <h1 className="text-[28px] font-medium leading-tight">任务</h1>
        <p className="mt-2 text-base text-dim">队列里没有任务。</p>
      </header>
      <GardenPhoto src="/garden/leaf.svg" label="茶树的叶子" />
      <div className="flex flex-wrap gap-2">
        {filters.map((label) => (
          <button
            key={label}
            type="button"
            aria-pressed={filter === label}
            onClick={() => setFilter(label)}
            className={`inline-flex h-11 items-center rounded-btn border px-3 text-sm ${
              filter === label ? 'border-tea/40 bg-panel text-paper' : 'border-line text-dim'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="overflow-x-auto rounded-card border border-line">
        <table className="w-full min-w-[860px] border-collapse text-left text-sm">
          <thead className="bg-panel text-dim">
            <tr>
              {taskColumns.map((column) => (
                <th key={column} className="px-4 py-3 font-medium">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="bg-ink">
            <tr>
              <td colSpan={taskColumns.length} className="px-4 py-16 text-center text-base text-dim">
                {filter === '全部' ? '还没有派发出去的任务。' : `「${filter}」下面是空的。`}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}
