"""
main.py — Discord 频道帖子搜索插件
为 AstrBot Agent 提供搜索 Discord 指定频道帖子的能力。
Agent 在用户询问推荐、攻略、卡组等信息时自动调用搜索 Tool。
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from astrbot.api import AstrBotConfig, FunctionTool, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools, register


# ============================================================================
# 常量
# ============================================================================

PLUGIN_NAME = "astrbot_plugin_discord_channel_search"
DEFAULT_REFRESH_INTERVAL = 600
DEFAULT_MAX_POSTS = 100


# ============================================================================
# 帖子缓存管理器
# ============================================================================

class PostCacheManager:
    """管理 Discord 帖子缓存的加载、更新、搜索和持久化。"""

    def __init__(self, cache_path: str) -> None:
        self.cache_path = cache_path
        self.posts: list[dict[str, Any]] = []
        self.last_refresh: float = 0.0

    def load(self) -> None:
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.posts = data.get("posts", [])
                self.last_refresh = data.get("last_refresh", 0.0)
                logger.info(f"[DiscordSearch] 加载缓存 {len(self.posts)} 条")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"[DiscordSearch] 缓存读取失败: {e}")
                self.posts = []

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"posts": self.posts, "last_refresh": self.last_refresh},
                    f, ensure_ascii=False, indent=2,
                )
        except OSError as e:
            logger.error(f"[DiscordSearch] 缓存保存失败: {e}")

    def update(self, channel_id: str, channel_name: str, posts: list[dict[str, Any]]) -> None:
        self.posts = [p for p in self.posts if p.get("channel_id") != channel_id]
        for post in posts:
            post["channel_name"] = channel_name
            post["channel_id"] = channel_id
        self.posts.extend(posts)
        self.last_refresh = time.time()

    def search(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        if not keyword.strip():
            return []
        keywords = [k.strip().lower() for k in keyword.split() if k.strip()]
        results: list[dict[str, Any]] = []
        for post in self.posts:
            text = ((post.get("title") or "") + " " + (post.get("content") or "")).lower()
            if any(kw in text for kw in keywords):
                results.append(post)
        results.sort(key=lambda p: p.get("created_at", ""), reverse=True)
        return results[:limit]


# ============================================================================
# Discord 频道帖子抓取器
# ============================================================================

class ChannelPostFetcher:
    """从 Discord 频道抓取帖子。"""

    @staticmethod
    def _is_forum_channel(channel: Any) -> bool:
        """自动判断是否为论坛频道。"""
        name = type(channel).__name__
        return "Forum" in name or "forum" in name.lower()

    @staticmethod
    async def fetch(client: Any, channel_id: int, limit: int) -> list[dict[str, Any]]:
        channel = client.get_channel(channel_id)
        if channel is None:
            logger.warning(f"[DiscordSearch] 频道 {channel_id} 未找到")
            return []

        try:
            if ChannelPostFetcher._is_forum_channel(channel):
                return await ChannelPostFetcher._forum(channel, limit)
            else:
                return await ChannelPostFetcher._history(channel, limit)
        except Exception as e:
            logger.error(f"[DiscordSearch] 抓取频道 {channel_id} 失败: {e}", exc_info=True)
            return []

    @staticmethod
    async def _forum(channel: Any, limit: int) -> list[dict[str, Any]]:
        posts: list[dict[str, Any]] = []
        if hasattr(channel, "threads"):
            for thread in channel.threads:
                if len(posts) >= limit:
                    break
                posts.append({
                    "id": str(thread.id),
                    "title": getattr(thread, "name", ""),
                    "author": thread.owner.display_name if hasattr(thread, "owner") and thread.owner else "Unknown",
                    "created_at": thread.created_at.isoformat() if hasattr(thread, "created_at") and thread.created_at else "",
                    "url": getattr(thread, "jump_url", ""),
                })
        return posts

    @staticmethod
    async def _history(channel: Any, limit: int) -> list[dict[str, Any]]:
        posts: list[dict[str, Any]] = []
        async for msg in channel.history(limit=limit):
            if not msg.content and not msg.attachments:
                continue
            posts.append({
                "id": str(msg.id),
                "title": msg.content[:100] + ("..." if len(msg.content) > 100 else ""),
                "content": msg.content[:500] if msg.content else "",
                "author": msg.author.display_name if hasattr(msg.author, "display_name") else "Unknown",
                "created_at": msg.created_at.isoformat(),
                "url": msg.jump_url if hasattr(msg, "jump_url") else "",
            })
        return posts


# ============================================================================
# Agent Tool: 搜索 Discord 频道帖子
# ============================================================================

@dataclass
class DiscordChannelSearchTool(FunctionTool):
    """搜索 Discord 指定频道中的帖子标题和内容。

    Agent 在用户询问推荐、查找卡牌、攻略等信息时自动调用此工具。
    """

    cache_manager: PostCacheManager | None = field(default=None, repr=False)
    fetcher: ChannelPostFetcher | None = field(default=None, repr=False)
    get_discord_clients: Any = field(default=None, repr=False)
    channels_config: list[dict[str, Any]] = field(default_factory=list, repr=False)
    max_posts: int = field(default=DEFAULT_MAX_POSTS, repr=False)
    _refresh_attempted: bool = field(default=False, init=False, repr=False)

    name: str = "discord_channel_search"
    description: str = (
        "搜索 Discord 指定频道中的帖子标题和内容。"
        "当用户询问推荐、有什么卡、找攻略、最新卡组、XX类卡等问题时使用此工具。"
        "用空格分隔的多关键词进行模糊搜索，如'水系 快攻 便宜'。"
        "建议：如用户之前表达过偏好，先调用 recall_long_term_memory 再搜索。"
    )
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词，空格分隔多个词进行模糊匹配，如'水系卡组'、'新手推荐 便宜'",
                },
            },
            "required": ["keyword"],
        }
    )

    async def run(self, event: AstrMessageEvent, keyword: str, **kwargs: Any) -> str:
        _ = event
        kw = (keyword or "").strip()
        if not kw:
            return "请提供搜索关键词。"

        if not self.cache_manager:
            return "插件未初始化完成，请稍后再试。"

        # 首次调用时拉取帖子（仅尝试一次，避免 Discord 不可用时重复请求）
        if not self.cache_manager.posts and not self._refresh_attempted:
            self._refresh_attempted = True
            await self._refresh()

        results = self.cache_manager.search(keyword=kw, limit=10)

        if not results:
            return (
                f'未在 Discord 频道中找到与 "{kw}" 相关的帖子。'
                "请尝试更换关键词，例如用更短或更通用的词搜索。"
            )

        lines = [f'搜索 "{kw}" 找到 {len(results)} 个相关帖子：\n']
        for i, post in enumerate(results, 1):
            title = post.get("title", "") or "无标题"
            url = post.get("url", "") or ""
            ch = post.get("channel_name", "") or "?"
            author = post.get("author", "") or "?"
            date = (post.get("created_at") or "")[:10]

            lines.append(f"{i}. {title}")
            if url:
                lines.append(f"   {url}  |  #{ch}  |  {author}  |  {date}")
            else:
                lines.append(f"   #{ch}  |  {author}  |  {date}")
            lines.append("")

        return "\n".join(lines)

    async def _refresh(self) -> None:
        if not self.get_discord_clients or not self.fetcher:
            return
        clients = self.get_discord_clients()
        if not clients:
            return
        client = clients[0]
        if not hasattr(client, "is_ready") or not client.is_ready():
            return

        for ch_cfg in self.channels_config:
            ch_id_str = str(ch_cfg.get("channel_id", "")).strip()
            ch_name = str(ch_cfg.get("channel_name", ch_id_str)).strip()
            if not ch_id_str:
                continue
            try:
                ch_id = int(ch_id_str)
            except (ValueError, TypeError):
                continue
            posts = await self.fetcher.fetch(client, ch_id, self.max_posts)
            self.cache_manager.update(ch_id_str, ch_name, posts)

        self.cache_manager.save()


# ============================================================================
# 插件主类
# ============================================================================

@register(
    "astrbot_plugin_discord_channel_search",
    "NLKASHEI",
    "搜索 Discord 指定频道的帖子，Agent 自动调用",
    "1.0.0",
    "https://github.com/NLKASHEI/astrbot_plugin_discord_channel_search",
)
class DiscordChannelSearchPlugin(Star):
    """Discord 频道帖子搜索插件。

    注册 discord_channel_search Tool 供 Agent 调用。
    用户询问推荐/攻略/卡组时，Agent 自动搜索 Discord 频道帖子。
    与 LivingMemory 的 recall_long_term_memory 在 Agent 层面自动联动。
    """

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config

        data_dir = str(StarTools.get_data_dir(PLUGIN_NAME))
        cache_path = os.path.join(data_dir, "post_cache.json")

        self.cache_manager = PostCacheManager(cache_path)
        self.cache_manager.load()
        self.fetcher = ChannelPostFetcher()

        try:
            max_posts = int(self.config.get("max_posts_per_channel", DEFAULT_MAX_POSTS))
        except (ValueError, TypeError):
            max_posts = DEFAULT_MAX_POSTS

        self._search_tool = DiscordChannelSearchTool(
            cache_manager=self.cache_manager,
            fetcher=self.fetcher,
            get_discord_clients=self._get_clients,
            channels_config=self.config.get("channels", []),
            max_posts=max_posts,
        )
        self.context.add_llm_tools(self._search_tool)
        logger.info("[DiscordSearch] Tool 已注册: discord_channel_search")

        self._refresh_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._start_refresh_loop()

        # 防刷屏标志位
        self._warned_no_clients = False
        self._last_error_log: float = 0.0

        lm = self.context.get_registered_star("LivingMemory")
        if lm is not None and lm.activated:
            logger.info("[DiscordSearch] LivingMemory 已检测，Agent 层面自动联动")

    def _get_clients(self) -> list[Any]:
        clients: list[Any] = []
        for inst in self.context.platform_manager.platform_insts:
            try:
                if inst.meta().name == "discord":
                    client = getattr(inst, "client", None)
                    if client is not None:
                        clients.append(client)
            except Exception:
                pass
        return clients

    def _start_refresh_loop(self) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def _refresh_loop(self) -> None:
        await asyncio.sleep(10)
        while not self._shutdown_event.is_set():
            try:
                await self._do_refresh()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log_rate_limited(f"[DiscordSearch] 后台刷新异常: {e}")

            try:
                interval = int(self.config.get("refresh_interval", DEFAULT_REFRESH_INTERVAL))
            except (ValueError, TypeError):
                interval = DEFAULT_REFRESH_INTERVAL
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=max(interval, 60),
                )
            except asyncio.TimeoutError:
                pass

    async def _do_refresh(self) -> None:
        channels_config = self.config.get("channels", [])
        if not channels_config:
            return
        clients = self._get_clients()
        if not clients:
            if not self._warned_no_clients:
                self._warned_no_clients = True
                logger.warning("[DiscordSearch] 未找到 Discord 客户端，请确认已配置 Discord 平台适配器")
            return
        self._warned_no_clients = False  # 恢复了就重置
        client = clients[0]
        if not hasattr(client, "is_ready") or not client.is_ready():
            return  # 启动阶段的正常状态，不记录日志

        try:
            max_posts = int(self.config.get("max_posts_per_channel", DEFAULT_MAX_POSTS))
        except (ValueError, TypeError):
            max_posts = DEFAULT_MAX_POSTS
        for ch_cfg in channels_config:
            ch_id_str = str(ch_cfg.get("channel_id", "")).strip()
            ch_name = str(ch_cfg.get("channel_name", ch_id_str)).strip()
            if not ch_id_str:
                continue
            try:
                ch_id = int(ch_id_str)
            except (ValueError, TypeError):
                continue
            try:
                posts = await self.fetcher.fetch(client, ch_id, max_posts)
                self.cache_manager.update(ch_id_str, ch_name, posts)
                logger.info(f"[DiscordSearch] #{ch_name} 获取 {len(posts)} 条")
            except Exception as e:
                self._log_rate_limited(f"[DiscordSearch] #{ch_name} 刷新失败: {e}")

        self.cache_manager.save()

    def _log_rate_limited(self, msg: str) -> None:
        """限速日志：同一条错误 5 分钟内只记录一次。"""
        now = time.time()
        if now - self._last_error_log > 300:
            self._last_error_log = now
            logger.error(msg, exc_info=True)
        else:
            logger.debug(msg)

    async def terminate(self) -> None:
        logger.info("[DiscordSearch] 正在卸载...")
        self._shutdown_event.set()
        if self._refresh_task is not None and not self._refresh_task.done():
            self._refresh_task.cancel()
            try:
                await asyncio.wait_for(self._refresh_task, timeout=5)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        self.context.provider_manager.llm_tools.remove_func(self._search_tool.name)
        self.cache_manager.save()
        logger.info("[DiscordSearch] 已卸载")
