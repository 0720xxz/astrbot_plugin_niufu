"""配置持久化模块 — 12组JSON文件的load/save、路径常量、默认配置"""
import json
from pathlib import Path
from astrbot.api import logger

PLUGIN_DIR = Path(__file__).parent

def _data_dir():
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path
        d = Path(get_astrbot_plugin_data_path()) / "astrbot_plugin_niufu"
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        d = Path.home() / ".astrbot" / "data" / "plugin_data" / "astrbot_plugin_niufu"
        d.mkdir(parents=True, exist_ok=True)
        return d

DATA_DIR = _data_dir()
TOGGLE_FILE = DATA_DIR / "toggle_state.json"
SERVER_DATA_FILE = DATA_DIR / "server_data.json"
BLACKLIST_FILE = DATA_DIR / "blacklist.json"
GROUP_BINDING_FILE = DATA_DIR / "group_bindings.json"
FUZZY_TOGGLE_FILE = DATA_DIR / "fuzzy_toggle.json"
GROUP_NOSLASH_FILE = DATA_DIR / "group_noslash.json"
SERVER_HISTORY_FILE = DATA_DIR / "server_history.json"
SERVER_CACHE_FILE = DATA_DIR / "server_cache.json"
COMMAND_LOGS_FILE = DATA_DIR / "command_logs.json"
ERROR_LOGS_FILE = DATA_DIR / "error_logs.json"
RAW_RESPONSES_FILE = DATA_DIR / "raw_responses.json"
PLAYER_LOGS_FILE = DATA_DIR / "player_logs.json"

DEFAULT_SERVER_DATA = {
    "refresh_interval_min": 30,
    "refresh_interval_max": 120,
    "refresh_decay_step": 15,
    "history_interval": 120,
    "cache_ttl": 60,
    "alert_drop_pct": 50,
    "alert_min_players": 20,
    "retract_seconds": 30,
    "trust_pool": {"主源": 5, "CN": 4, "MH": 3},
    "webhook_url": "https://scpslpost.1685153300.workers.dev/api/status",
    "webhook_secret": "",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "group_headers": {
        "内战组": ["--- 通用服务器框架 ---", "=================="]
    },
    "servers": [
        {"id": "59288", "group": "内战组", "default_name": "示范服1", "display_name": "测试服务器"}
    ]
}

def load_server_data():
    if SERVER_DATA_FILE.exists():
        try:
            with open(SERVER_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "group_headers" not in data:
                    data["group_headers"] = DEFAULT_SERVER_DATA["group_headers"].copy()
                return data
        except Exception as e:
            logger.warning(f"[服务器框架] 配置文件损坏 {SERVER_DATA_FILE}: {e}，使用默认值")
    else:
        try:
            with open(SERVER_DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_SERVER_DATA, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return dict(DEFAULT_SERVER_DATA)

def save_server_data(data):
    with open(SERVER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

GLOBAL_DATA = load_server_data()

def _get_toggle_key(group: str, default_name: str) -> str:
    return f"{group}::{default_name}"

def load_toggle_state():
    if TOGGLE_FILE.exists():
        try:
            with open(TOGGLE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"[服务器框架] 配置文件损坏 {TOGGLE_FILE}: {e}")
    return {_get_toggle_key(s["group"], s["default_name"]): True for s in GLOBAL_DATA["servers"]}

def save_toggle_state(state):
    with open(TOGGLE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def load_blacklist():
    if BLACKLIST_FILE.exists():
        try:
            with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"groups": [], "users": []}

def save_blacklist(data):
    with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_group_bindings():
    if GROUP_BINDING_FILE.exists():
        try:
            with open(GROUP_BINDING_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_group_bindings(bindings):
    with open(GROUP_BINDING_FILE, "w", encoding="utf-8") as f:
        json.dump(bindings, f, ensure_ascii=False, indent=2)

def load_fuzzy_toggle():
    if FUZZY_TOGGLE_FILE.exists():
        try:
            with open(FUZZY_TOGGLE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_fuzzy_toggle(data):
    with open(FUZZY_TOGGLE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_fuzzy_enabled(group_id: str, fuzzy_toggle_data: dict) -> bool:
    return fuzzy_toggle_data.get(group_id, True)

def load_group_noslash():
    if GROUP_NOSLASH_FILE.exists():
        try:
            with open(GROUP_NOSLASH_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_group_noslash(data):
    with open(GROUP_NOSLASH_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_noslash_enabled(group_name: str, noslash_data: dict) -> bool:
    return noslash_data.get(group_name, False)

def load_server_history():
    if SERVER_HISTORY_FILE.exists():
        try:
            with open(SERVER_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_server_history(data):
    with open(SERVER_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_server_cache():
    if SERVER_CACHE_FILE.exists():
        try:
            with open(SERVER_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_server_cache(data):
    with open(SERVER_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_command_logs():
    if COMMAND_LOGS_FILE.exists():
        try:
            with open(COMMAND_LOGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_command_logs(data):
    with open(COMMAND_LOGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_error_logs():
    if ERROR_LOGS_FILE.exists():
        try:
            with open(ERROR_LOGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_error_logs(data):
    with open(ERROR_LOGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_raw_responses():
    if RAW_RESPONSES_FILE.exists():
        try:
            with open(RAW_RESPONSES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_raw_responses(data):
    with open(RAW_RESPONSES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_player_logs():
    if PLAYER_LOGS_FILE.exists():
        try:
            with open(PLAYER_LOGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_player_logs(data):
    with open(PLAYER_LOGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
