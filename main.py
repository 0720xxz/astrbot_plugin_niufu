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
          