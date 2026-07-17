# Discord 频道帖子搜索插件

为 AstrBot Agent 提供 Discord 频道帖子搜索能力。用户询问推荐、攻略、卡组等信息时，Agent 自动搜索配置的 Discord 频道帖子并返回匹配结果。

与 [LivingMemory](https://github.com/lxfight-s-Astrbot-Plugins/astrbot_plugin_livingmemory) 的 `recall_long_term_memory` 在 Agent 层面自动联动。

## 功能

- 自动搜索指定 Discord 频道（论坛频道 + 普通文字频道）的帖子标题和内容
- 纯 Agent Tool 驱动，**无需手动输入任何指令**
- 多关键词模糊搜索
- 定时后台刷新帖子缓存
- 与 LivingMemory 联动：Agent 先查用户偏好，再精准搜索

## 安装

在 AstrBot WebUI → 插件市场搜索 `discord_channel_search` 安装，或手动克隆到 `data/plugins/`：

```bash
cd AstrBot/data/plugins
git clone https://github.com/NLKASHEI/astrbot_plugin_discord_channel_search.git
```

## 配置

在 AstrBot WebUI → 插件管理 → 找到本插件 → 配置面板：

1. **添加频道**：点击「添加频道配置」，填写：
   - `channel_id`：Discord 频道 ID（右键频道 → 复制ID，需开启开发者模式）
   - `channel_name`：显示名称（如「卡组推荐」「攻略分享」）
   - `is_forum`：是否为论坛频道
2. 可反复添加多个频道
3. `refresh_interval`：缓存刷新间隔，默认 600 秒（10 分钟）
4. `max_posts_per_channel`：每个频道最大缓存帖子数，默认 100

## 使用

**无需手动指令。** 用户对话示例：

```
用户：推荐一些水系卡组
Agent → 调用 recall_long_term_memory 查偏好
Agent → 调用 discord_channel_search 搜帖子
回复：找到 3 个相关帖子：
1. 【攻略】水系快攻卡组推荐 — #卡组推荐
   https://discord.com/channels/...
2. 新手水系卡组指南 — #攻略分享
   ...
```

## 依赖

无额外依赖。AstrBot 的 Discord 适配器已自带 `py-cord`。

## 兼容性

- AstrBot >= 4.24
- 需配置 Discord 平台适配器
- LivingMemory（可选，Agent 层面自动联动）
