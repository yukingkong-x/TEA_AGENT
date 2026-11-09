# 分支与协作约定

> 场景：同一个 GitHub 账号在两台机器（两个目录）上同时开发，容易互相踩。下面是定死的规则。

## 一、命名规则

```
feature/<谁>-<干什么>      新功能
fix/<谁>-<修什么>          修 bug
chore/<干什么>             杂务（配置、脚手架、文档格式）
```

`<谁>` 用**角色/地盘**，不用人名（人名会变，地盘不会）：

| 地盘 | 前缀 | 例子 |
| --- | --- | --- |
| 智能体/编排（队长） | `agents-` | `feature/agents-runner` |
| 后端基座（队友 B） | `backend-` | `feature/backend-base`、`feature/backend-simulator` |
| 前端大屏（队友 A） | `web-` | `feature/web-dashboard` |

**唯一硬性要求：两条线的前缀不能重叠。** 同一个账号推同名的分支，后推的会覆盖前推的（非快进会被拒，但一旦误 force push 就没了）。

当前分支：`feature/backend-base`（基座线）——已符合上述规则，不改名。

## 二、五条纪律

1. **一律从 `origin/main` 开分支**，不要从别人的 feature 分支开（会把别人未合并的提交一起带进来）。
2. **只 add 自己地盘的路径**，禁止 `git add -A` / `git add .`。
3. **提交前 `git status` 看一遍**，发现自己地盘以外的文件被改动 → 别提交，先查是谁动的。
4. **一个工作目录只能有一个 HEAD**。两边共用一个文件夹会互相切分支、删文件；正确做法是 `git worktree`：

   ```bash
   git worktree add ../TEA_AGENT_backend feature/backend-base
   git worktree list          # 看有几个工作树
   git worktree remove ../xxx # 用完回收
   ```

5. **PR 只往 `main` 提**，不带别人的半成品。合并前先 `git fetch origin && git rebase origin/main`。

## 三、提交信息

```
feat(backend): 六服务 compose + 14 表建模
fix(backend): mosquitto 具名卷权限导致重启循环
chore: gitignore 加 .workbuddy/
```

`type(scope): 做了什么`，正文写「为什么」和「验证过什么」。一条提交只做一件事。
