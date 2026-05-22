import json
import asyncio
from pathlib import Path
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Star, Context, register
from astrbot.api import logger
import aiohttp
import astrbot.api.message_components as Comp

PLUGIN_SERVERS = ["鸢神祈冬#1", "鸢神祈冬#2", "鸢神祈冬#3", "鸢神祈冬#4", "鸢神祈冬#5", "鸢神祈冬#6"]
PURE_SERVERS = ["原神高手#1", "原神高手#2", "原神高手#3", "原神高手#4", "原神高手#5", "原神高手#6"]
ALL_SERVERS = PLUGIN_SERVERS + PURE_SERVERS

URL_MAP = {
    "鸢神祈冬#1": "https://api.scplist.kr/api/servers/59288",
    "鸢神祈冬#2": "https://api.scplist.kr/api/servers/72039",
    "鸢神祈冬#3": "https://api.scplist.kr/api/servers/102637",
    "鸢神祈冬#4": "https://api.scplist.kr/api/servers/72041",
    "鸢神祈冬#5": "https://api.scplist.kr/api/servers/99987",
    "鸢神祈冬#6": "https://api.scplist.kr/api/servers/72044",
    "原神高手#1": "https://api.scplist.kr/api/servers/101108",
    "原神高手#2": "https://api.scplist.kr/api/servers/71164",
    "原神高手#3": "https://api.scplist.kr/api/servers/71165",
    "原神高手#4": "https://api.scplist.kr/api/servers/71166",
    "原神高手#5": "https://api.scplist.kr/api/servers/71167",
    "原神高手#6": "https://api.scplist.kr/api/servers/101594",
}

GROUP_MAP = {"插件": PLUGIN_SERVERS, "纯净": PURE_SERVERS}
PLUGIN_DIR = Path(__file__).parent
TOGGLE_FILE = PLUGIN_DIR / "toggle_state.json"

PIGEON_SERVERS = {
    "鸽子一服": "https://api.scplist.kr/api/servers/99742",
    "鸽子二服": "https://api.scplist.kr/api/servers/99743",
    "鸽子三服": "https://api.scplist.kr/api/servers/99744",
    "鸽子四服": "https://api.scplist.kr/api/servers/99745",
    "鸽子五服": "https://api.scplist.kr/api/servers/99746",
}
PIGEON_TOGGLE_FILE = PLUGIN_DIR / "pigeon_toggle.json"


def load_toggle_state():
    if TOGGLE_FILE.exists():
        with open(TOGGLE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {name: True for name in ALL_SERVERS}


def save_toggle_state(state):
    with open(TOGGLE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_pigeon_state():
    if PIGEON_TOGGLE_FILE.exists():
        with open(PIGEON_TOGGLE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {name: True for name in PIGEON_SERVERS}


def save_pigeon_state(state):
    with open(PIGEON_TOGGLE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def find_cmd_config():
    """
    精准查找真正在运行的 data/cmd_config.json 路径。
    从插件所在的目录向上寻找包含 data 文件夹且含有 cmd_config.json 的位置。
    """
    current = Path(__file__).resolve().parent
    
    for _ in range(5):
        data_json = current / "data" / "cmd_config.json"
        if data_json.exists():
            return data_json
        current = current.parent

    
    paths_to_check = [
        Path.cwd() / "data" / "cmd_config.json",
        Path.cwd() / "cmd_config.json",
        Path(__file__).parent / "cmd_config.json"
    ]
    for p in paths_to_check:
        if p.exists():
            return p
            
    return Path.cwd() / "data" / "cmd_config.json"


async def get_admin_list():
    config_path = find_cmd_config()
    if not config_path.exists():
        logger.warning(f"[牛服插件] 未找到配置文件: {config_path}")
        return []
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        admins = config.get("admins_id", [])
        return [str(uid) for uid in admins]
    except Exception as e:
        logger.error(f"[牛服插件] 读取管理员列表失败: {e}")
        return []


async def save_admin_list(admin_list):
    config_path = find_cmd_config()
    try:
        if not config_path.exists():
            
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"admins_id": admin_list}, f, ensure_ascii=False, indent=2)
            return
            
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            
        config["admins_id"] = admin_list
        
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
            
        logger.info(f"[牛服插件] 成功同步管理员列表至文件: {config_path}")
    except Exception as e:
        logger.error(f"[牛服插件] 保存管理员列表失败: {e}")


def is_admin(sender_id: str, admin_list: list) -> bool:
    if not admin_list:
        return False
    return str(sender_id) in admin_list


@register("astrbot_plugin_niufu", "niufu", "query", "1.1.0")
class NiufuPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.toggle_state = load_toggle_state()
        self.cache = {"niufu": [], "ip": []}
        self.refresh_task = None
        self.refresh_interval = 30  
        self.pigeon_state = load_pigeon_state()
        self.pigeon_cache = []
        self.pigeon_refresh_task = None
        self.pigeon_refresh_interval = 30  

    async def _fetch(self, url):
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                return await resp.json()

    async def _build_niufu(self):
        lines = ["鸢神祈冬&原神高手", "原大牛牛", "=============="]
        for name in PLUGIN_SERVERS:
            if not self.toggle_state.get(name, True):
                continue
            try:
                data = await self._fetch(URL_MAP[name])
                players = data.get("players", 0)
                max_players = data.get("max_players")
                display_name = "内测" if name == "鸢神祈冬#5" else name
                if max_players is not None:
                    lines.append(f"{display_name} {players}/{max_players}")
                else:
                    lines.append(f"{display_name} {players}")
            except Exception:
                pass
        lines.append("==============")
        for name in PURE_SERVERS:
            if not self.toggle_state.get(name, True):
                continue
            try:
                data = await self._fetch(URL_MAP[name])
                players = data.get("players", 0)
                max_players = data.get("max_players")
                if max_players is not None:
                    lines.append(f"{name} {players}/{max_players}")
                else:
                    lines.append(f"{name} {players}")
            except Exception:
                pass
        lines.append("==============")
        return lines

    async def _build_ip(self):
        lines = ["鸢神祈冬&原神高手", "原大牛牛", "=============="]
        for name in PLUGIN_SERVERS:
            if not self.toggle_state.get(name, True):
                continue
            if name == "鸢神祈冬#4":
                lines.append(f"{name} 史头不喜欢这个数")
                continue
            try:
                data = await self._fetch(URL_MAP[name])
                ip = data.get("ip", "")
                port = data.get("port", "")
                display_name = "内测" if name == "鸢神祈冬#5" else name
                if ip and port:
                    lines.append(f"{display_name} {ip}:{port}")
                else:
                    lines.append(f"{display_name} 史头不喜欢这个数")
            except Exception:
                lines.append(f"{name} 查询失败")
        lines.append("==============")
        for name in PURE_SERVERS:
            if not self.toggle_state.get(name, True):
                continue
            if name == "原神高手#4":
                lines.append(f"{name} 史头不喜欢这个数")
                continue
            try:
                data = await self._fetch(URL_MAP[name])
                ip = data.get("ip", "")
                port = data.get("port", "")
                if ip and port:
                    lines.append(f"{name} {ip}:{port}")
                else:
                    lines.append(f"{name} 史头不喜欢这个数")
            except Exception:
                lines.append(f"{name} 查询失败")
        lines.append("==============")
        return lines

    async def _build_pigeon(self):
        lines = ["大唐合鸟子社区", "============"]
        for name, url in PIGEON_SERVERS.items():
            if not self.pigeon_state.get(name, True):
                continue
            try:
                data = await self._fetch(url)
                players = data.get("players", 0)
                max_players = data.get("max_players")
                if max_players is not None:
                    lines.append(f"{name} {players}/{max_players}")
                else:
                    lines.append(f"{name} {players}")
            except Exception:
                pass
        lines.append("============")
        return lines

    async def _refresh_loop(self):
        while True:
            try:
                self.cache["niufu"] = await self._build_niufu()
                self.cache["ip"] = await self._build_ip()
            except Exception:
                pass
            await asyncio.sleep(self.refresh_interval)

    async def _refresh_pigeon_loop(self):
        while True:
            try:
                self.pigeon_cache = await self._build_pigeon()
            except Exception:
                pass
            await asyncio.sleep(self.pigeon_refresh_interval)

    def _start_all_polling(self):
        if self.refresh_task is None or self.refresh_task.done():
            self.refresh_task = asyncio.create_task(self._refresh_loop())
        if self.pigeon_refresh_task is None or self.pigeon_refresh_task.done():
            self.pigeon_refresh_task = asyncio.create_task(self._refresh_pigeon_loop())

    async def _force_refresh_all(self):
        try:
            self.cache["niufu"] = await self._build_niufu()
            self.cache["ip"] = await self._build_ip()
            self.pigeon_cache = await self._build_pigeon()
        except Exception:
            pass

    def _reply_at(self, event, text):
        if event.is_private_chat():
            yield event.plain_result(text)
        else:
            chain = [Comp.At(qq=event.get_sender_id()), Comp.Plain(f"\n{text}")]
            yield event.chain_result(chain)

    @filter.command("help")
    async def help_cmd(self, event: AstrMessageEvent):
        help_text = """📖 牛服插件使用帮助

查询命令
/牛服 - 查看已启用服务器的在线人数
/ip   - 查看已启用服务器的IP地址和端口
/鸽服 - 查看大唐合鸟子社区在线人数

开关命令（仅管理员可用）
/启用端口 <类型><编号>   - 启用指定服务器
/禁用端口 <类型><编号>   - 禁用指定服务器
/启用端口 所有          - 启用所有服务器
/禁用端口 所有          - 禁用所有服务器
/启用端口 所有插件       - 启用所有鸢神祈冬服务器
/禁用端口 所有插件       - 禁用所有鸢神祈冬服务器
/启用端口 所有纯净       - 启用所有原神高手服务器
/禁用端口 所有纯净       - 禁用所有原神高手服务器

鸽服开关命令（仅管理员可用）
/启用鸽服 <编号>        - 启用指定鸽服（1-5）
/禁用鸽服 <编号>        - 禁用指定鸽服（1-5）
/启用鸽服 所有          - 启用所有鸽服
/禁用鸽服 所有          - 禁用所有鸽服"""
        for chunk in self._reply_at(event, help_text):
            yield chunk

    @filter.command("牛服")
    async def niufu(self, event: AstrMessageEvent):
        if not self.cache["niufu"]:
            self.cache["niufu"] = await self._build_niufu()
        for chunk in self._reply_at(event, "\n".join(self.cache["niufu"])):
            yield chunk
        self._start_all_polling()

    @filter.command("ip")
    async def ip(self, event: AstrMessageEvent):
        if not self.cache["ip"]:
            self.cache["ip"] = await self._build_ip()
        for chunk in self._reply_at(event, "\n".join(self.cache["ip"])):
            yield chunk
        self._start_all_polling()

    @filter.command("鸽服")
    async def pigeon_cmd(self, event: AstrMessageEvent):
        if not self.pigeon_cache:
            self.pigeon_cache = await self._build_pigeon()
        result = "\n".join(self.pigeon_cache)
        for chunk in self._reply_at(event, result):
            yield chunk
        self._start_all_polling()

    @filter.command("启用端口")
    async def enable(self, event: AstrMessageEvent):
        admin_list = await get_admin_list()
        if not is_admin(str(event.get_sender_id()), admin_list):
            return
        msg = event.get_message_str().strip()
        parts = msg.split(maxsplit=1)
        if len(parts) < 2:
            for chunk in self._reply_at(event, "用法：/启用端口 <插件|纯净><编号> 或 /启用端口 所有"):
                yield chunk
            return
        target = parts[1].strip()
        if target == "所有":
            for name in ALL_SERVERS:
                self.toggle_state[name] = True
            save_toggle_state(self.toggle_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, "已启用所有服务器"):
                yield chunk
        elif target == "所有插件":
            for name in GROUP_MAP["插件"]:
                self.toggle_state[name] = True
            save_toggle_state(self.toggle_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, "已启用所有插件服务器"):
                yield chunk
        elif target == "所有纯净":
            for name in GROUP_MAP["纯净"]:
                self.toggle_state[name] = True
            save_toggle_state(self.toggle_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, "已启用所有纯净服务器"):
                yield chunk
        elif target.startswith("插件"):
            num = target[2:]
            if not num.isdigit():
                for chunk in self._reply_at(event, "格式错误，请使用如：/启用端口 插件1"):
                    yield chunk
                return
            name = f"鸢神祈冬#{num}"
            if name in URL_MAP:
                self.toggle_state[name] = True
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, f"已启用：{name}"):
                    yield chunk
            else:
                for chunk in self._reply_at(event, f"未找到插件{num}"):
                    yield chunk
        elif target.startswith("纯净"):
            num = target[2:]
            if not num.isdigit():
                for chunk in self._reply_at(event, "格式错误，请使用如：/启用端口 纯净1"):
                    yield chunk
                return
            name = f"原神高手#{num}"
            if name in URL_MAP:
                self.toggle_state[name] = True
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, f"已启用：{name}"):
                    yield chunk
            else:
                for chunk in self._reply_at(event, f"未找到纯净{num}"):
                    yield chunk
        else:
            for chunk in self._reply_at(event, "无效的格式，请使用：插件编号 或 纯净编号，例如：插件1，纯净2"):
                yield chunk

    @filter.command("禁用端口")
    async def disable(self, event: AstrMessageEvent):
        admin_list = await get_admin_list()
        if not is_admin(str(event.get_sender_id()), admin_list):
            return
        msg = event.get_message_str().strip()
        parts = msg.split(maxsplit=1)
        if len(parts) < 2:
            for chunk in self._reply_at(event, "用法：/禁用端口 <插件|纯净><编号> 或 /禁用端口 所有"):
                yield chunk
            return
        target = parts[1].strip()
        if target == "所有":
            for name in ALL_SERVERS:
                self.toggle_state[name] = False
            save_toggle_state(self.toggle_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, "已禁用所有服务器"):
                yield chunk
        elif target == "所有插件":
            for name in GROUP_MAP["插件"]:
                self.toggle_state[name] = False
            save_toggle_state(self.toggle_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, "已禁用所有插件服务器"):
                yield chunk
        elif target == "所有纯净":
            for name in GROUP_MAP["纯净"]:
                self.toggle_state[name] = False
            save_toggle_state(self.toggle_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, "已禁用所有纯净服务器"):
                yield chunk
        elif target.startswith("插件"):
            num = target[2:]
            if not num.isdigit():
                for chunk in self._reply_at(event, "格式错误，请使用如：/禁用端口 插件1"):
                    yield chunk
                return
            name = f"鸢神祈冬#{num}"
            if name in URL_MAP:
                self.toggle_state[name] = False
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, f"已禁用：{name}"):
                    yield chunk
            else:
                for chunk in self._reply_at(event, f"未找到插件{num}"):
                    yield chunk
        elif target.startswith("纯净"):
            num = target[2:]
            if not num.isdigit():
                for chunk in self._reply_at(event, "格式错误，请使用如：/禁用端口 纯净1"):
                    yield chunk
                return
            name = f"原神高手#{num}"
            if name in URL_MAP:
                self.toggle_state[name] = False
                save_toggle_state(self.toggle_state)
                await self._force_refresh_all()
                for chunk in self._reply_at(event, f"已禁用：{name}"):
                    yield chunk
            else:
                for chunk in self._reply_at(event, f"未找到纯净{num}"):
                    yield chunk
        else:
            for chunk in self._reply_at(event, "无效的格式，请使用：插件编号 或 纯净编号，例如：插件1，纯净2"):
                yield chunk

    @filter.command("启用鸽服")
    async def enable_pigeon(self, event: AstrMessageEvent):
        admin_list = await get_admin_list()
        if not is_admin(str(event.get_sender_id()), admin_list):
            return
        msg = event.get_message_str().strip()
        parts = msg.split(maxsplit=1)
        if len(parts) < 2:
            for chunk in self._reply_at(event, "用法：/启用鸽服 <编号> 或 /启用鸽服 所有"):
                yield chunk
            return
        target = parts[1].strip()
        if target == "所有":
            for name in PIGEON_SERVERS:
                self.pigeon_state[name] = True
            save_pigeon_state(self.pigeon_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, "已启用所有鸽服"):
                yield chunk
        elif target.isdigit() and 1 <= int(target) <= 5:
            name = f"鸽子{['一','二','三','四','五'][int(target)-1]}服"
            self.pigeon_state[name] = True
            save_pigeon_state(self.pigeon_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, f"已启用：{name}"):
                yield chunk
        else:
            for chunk in self._reply_at(event, "无效的编号，请使用 1-5 或 所有"):
                yield chunk

    @filter.command("禁用鸽服")
    async def disable_pigeon(self, event: AstrMessageEvent):
        admin_list = await get_admin_list()
        if not is_admin(str(event.get_sender_id()), admin_list):
            return
        msg = event.get_message_str().strip()
        parts = msg.split(maxsplit=1)
        if len(parts) < 2:
            for chunk in self._reply_at(event, "用法：/禁用鸽服 <编号> 或 /禁用鸽服 所有"):
                yield chunk
            return
        target = parts[1].strip()
        if target == "所有":
            for name in PIGEON_SERVERS:
                self.pigeon_state[name] = False
            save_pigeon_state(self.pigeon_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, "已禁用所有鸽服"):
                yield chunk
        elif target.isdigit() and 1 <= int(target) <= 5:
            name = f"鸽子{['一','二','三','四','五'][int(target)-1]}服"
            self.pigeon_state[name] = False
            save_pigeon_state(self.pigeon_state)
            await self._force_refresh_all()
            for chunk in self._reply_at(event, f"已禁用：{name}"):
                yield chunk
        else:
            for chunk in self._reply_at(event, "无效的编号，请使用 1-5 或 所有"):
                yield chunk

    @filter.command("管理")
    async def admin_command(self, event: AstrMessageEvent):
        admin_list = await get_admin_list()
        sender_id = str(event.get_sender_id())
        
        if not is_admin(sender_id, admin_list):
            return
            
        msg = event.get_message_str().strip()
        parts = msg.split(maxsplit=2)
        if len(parts) < 2:
            for chunk in self._reply_at(event, "用法：/管理 add <QQ号> 或 /管理 remove <QQ号> 或 /管理 list"):
                yield chunk
            return
            
        subcmd = parts[1].lower()

        if subcmd == "list":
            if not admin_list:
                for chunk in self._reply_at(event, "当前没有管理员"):
                    yield chunk
            else:
                lines = ["当前管理员列表："] + [f"{i+1}. {uid}" for i, uid in enumerate(admin_list)]
                for chunk in self._reply_at(event, "\n".join(lines)):
                    yield chunk
            return

        if len(parts) < 3:
            for chunk in self._reply_at(event, "请提供QQ号"):
                yield chunk
            return
            
        qq = parts[2].strip()
        if not qq.isdigit():
            for chunk in self._reply_at(event, "QQ号必须为纯数字"):
                yield chunk
            return

        if subcmd == "add":
            if qq in admin_list:
                for chunk in self._reply_at(event, f"QQ {qq} 已经是管理员了"):
                    yield chunk
            else:
                admin_list.append(qq)
                await save_admin_list(admin_list)
                for chunk in self._reply_at(event, f"已成功添加 {qq} 为管理员"):
                    yield chunk
                    
        elif subcmd in ("remove", "del"):
            if qq not in admin_list:
                for chunk in self._reply_at(event, f"QQ {qq} 本来就不是管理员"):
                    yield chunk
            else:
                admin_list.remove(qq)
                await save_admin_list(admin_list)
                for chunk in self._reply_at(event, f"已成功移除 {qq} 的管理员权限"):
                    yield chunk
        else:
            for chunk in self._reply_at(event, "未知子命令，可用：add, remove, list"):
                yield chunk
