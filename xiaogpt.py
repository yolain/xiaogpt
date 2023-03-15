import threading
import asyncio
import time
import json
import os
from http.cookies import SimpleCookie
from requests.utils import cookiejar_from_dict
from pathlib import Path
from aiohttp import ClientSession
from miservice import MiAccount, MiNAService, MiIOService, miio_command
from V3 import Chatbot

def load_json():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    else:
        raise Exception(f"{CONFIG_PATH} doesn't exist")
def save_json(data):
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    else:
        raise Exception(f"{CONFIG_PATH} doesn't exist")

def parse_cookie_string(cookie_string):
    cookie = SimpleCookie()
    cookie.load(cookie_string)
    cookies_dict = {}
    cookiejar = None
    for k, m in cookie.items():
        cookies_dict[k] = m.value
        cookiejar = cookiejar_from_dict(cookies_dict, cookiejar=None, overwrite=True)
    return cookiejar

class ChatGptBox:
    def __init__(self, session, openai_key, openai_baseurl):
        self.session = session
        self.openai_key = openai_key
        self.openai_baseurl = openai_baseurl
        self.history = []

    async def ask(self, query):
        api_url = self.openai_baseurl + '/v1/chat/completions'
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.openai_key}",
        }
        ms = []
        new_query = {"role": "user", "content": f"{query}"}
        for h in self.history:
            ms.append(h)
        ms.append(new_query)

        data = {
            "model": "gpt-3.5-turbo",
            "messages": ms
        }
        res = await self.session.post(api_url, headers=headers, json=data, ssl=False)
        completion = await res.json()
        message = (
            completion["choices"][0]
            .get("message")
            .get("content")
            .encode("utf8")
            .decode()
        )
        self.history.append(new_query)
        self.history.append({"role": "assistant", "content": message})
        # only keep 10 history
        self.history = self.history[-10:]
        return message

class MiGPT:
    def __init__(self, options):
        self.mi_token_home = Path.home() / ".mi.token"
        self.last_timestamp = 0     # timestamp last call mi speaker
        self.session = None
        self.mina_service = None
        self.cookie = None
        self.chatbot = None
        # 配置信息
        self.last_ask_api = "https://userprofile.mina.mi.com/device_profile/v2/conversation?source=dialogu&hardware={hardware}&timestamp={timestamp}&limit=2"
        self.cookie_template = "deviceId={device_id}; serviceToken={service_token}; userId={user_id}"
        self.token_info = options['token_info']
        self.hardware = options['hardware']
        self.account = options['account']
        self.password = options['password']
        self.openai_key = options['openai_key']
        self.openai_baseurl = options['openai_baseurl']
        self.end_prompt = options['end_prompt']
        self.keep_chat = options['keep_chat']
        self.use_command = options['use_command']
        self.tts_command = self.hardware_command_dict(options['hardware'])
        self.proxy = options['proxy']

    def hardware_command_dict(self, hardware):
        return {
            "LX06": "5-1",
            "L05B": "5-3",
            "S12A": "5-1",
            "LX01": "5-1",
            "L06A": "5-1",
            "LX04": "5-1",
            "L05C": "5-3",
            "L17A": "7-3",
            "X08E": "7-3",
        }.get(hardware, "5-1")

    async def test_command(self, value):
        async with ClientSession() as session:
            await self.init_miaccount(session)
            self.session = session
            print(await miio_command(self.miio_service, self.token_info['mi_did'], value))

    async def play_voice(self, value):
        async with ClientSession() as session:
            await self.init_miaccount(session)
            self.session = session
            await self.do_tts(value)

    async def mute_xiaoai(self):
        # 强制停止小爱同学的回答（需要use_command的设备）
        if self.use_command:
            await self.mina_service.player_pause(self.token_info['device_id'])
        else:
            await self.stop_if_xiaoai_is_playing()
    async def check_new_query(self, session):
        try:
            r = await self.get_latest_ask_from_xiaoai()
        except Exception:
            # we try to init all again
            await self.init_all_data(session)
            r = await self.get_latest_ask_from_xiaoai()
        new_timestamp, last_record = self.get_last_timestamp_and_record(r)
        if new_timestamp > self.last_timestamp:
            return new_timestamp, last_record.get("query", "")
        return False, None
    async def to_chat(self):
        print('\033[1;33m' + '正在运行小爱同学GPT版本' + '\033[0m')
        SWITCH = False
        async with ClientSession() as session:
            await self.init_all_data(session)
            while True:
                try:
                    r = await self.get_latest_ask_from_xiaoai()
                except Exception:
                    # we try to init all again
                    await self.init_all_data(session)
                    r = await self.get_latest_ask_from_xiaoai()
                    # spider rule
                new_timestamp, last_record = self.get_last_timestamp_and_record(r)
                if new_timestamp > self.last_timestamp:
                    self.last_timestamp = new_timestamp
                    query = last_record.get("query", "")
                    if query.startswith('闭嘴') or query.startswith('停止'):
                        await self.stop_if_xiaoai_is_playing()
                        continue
                    if query.startswith('打开高级对话') or query.startswith('开启高级对话'):
                        await self.mute_xiaoai()
                        SWITCH = True
                        print("\033[1;32m高级对话已开启\033[0m")
                        if self.use_command:
                            await miio_command(self.miio_service, self.token_info['mi_did'], '5-4 小爱同学 0')
                        else:
                            await self.do_tts("高级对话已开启")
                        continue
                    if query.startswith('关闭高级对话'):
                        await self.mute_xiaoai()
                        SWITCH = False
                        print("\033[1;32m高级对话已关闭\033[0m")
                        await self.do_tts("高级对话已关闭")
                        continue
                    # 让触发词为小爱同学时执行持续性对话
                    if query.startswith("小爱同学") and self.keep_chat:
                        continue
                    # 判断包含关键词或不设置时触发
                    if SWITCH:
                        commas = 0
                        wait_times = 3
                        await self.mute_xiaoai()
                        query = f"{query}，{self.end_prompt}"
                        print('\033[1;34m' + "我: " + '\033[0m', end="")
                        print(query)
                        print('\033[1;34m' + "ChatGPT: " + '\033[0m', end="")
                        lock = threading.Lock()
                        stop_event = threading.Event()
                        thread = threading.Thread(target=self.chatbot.ask_stream, args=(query, lock, stop_event,))
                        thread.start()
                        is_playing = False
                        while True:
                            success = lock.acquire(blocking=False)
                            if success:  # 如果成功获取锁
                                try:
                                    this_sentence = self.chatbot.sentence  # 获取句子（目前的）
                                    if this_sentence == "" and not thread.is_alive():
                                        break
                                    is_a_sentence = False
                                    for x in (("，", "。", "？", "！", "；", ",", ".", "?", "!", ";")
                                    if commas <= wait_times else ("。", "？", "！", "；", ".", "?", "!", ";")):
                                        pos = this_sentence.rfind(x)
                                        if pos != -1:
                                            is_a_sentence = True
                                            # 取出完整的句组，剩下的放回去
                                            self.chatbot.sentence = this_sentence[pos + 1:]
                                            this_sentence = this_sentence[:pos + 1]
                                            break
                                finally:
                                    lock.release()
                            else:
                                time.sleep(0.01)
                                continue
                            if not is_a_sentence:
                                time.sleep(0.01)
                                continue
                            if not await self.get_if_xiaoai_is_playing():
                                if commas <= wait_times:
                                    commas += sum([1 for x in this_sentence if
                                                   x in {"，", "。", "？", "！", "；", ",", ".", "?", "!", ";"}]) + 1
                                is_playing = True
                                await self.do_tts(this_sentence)
                                if self.use_command:
                                    length = len(this_sentence)
                                    if length < 5:
                                        sleep_time = len(this_sentence) / 5
                                    elif length < 10:
                                        sleep_time = len(this_sentence) / 4
                                    elif length < 20:
                                        sleep_time = len(this_sentence) / 3
                                    else:
                                        sleep_time = len(this_sentence) / 2.5
                                    time.sleep(sleep_time)
                                    is_playing = False
                                if self.use_command:
                                    while is_playing and not \
                                            (await self.check_new_query(session))[0]:
                                        await asyncio.sleep(0.1)
                                else:
                                    while await self.get_if_xiaoai_is_playing() and not \
                                            (await self.check_new_query(session))[0]:
                                        await asyncio.sleep(0.1)
                                time_stamp, query = await self.check_new_query(session)
                                if time_stamp:
                                    stop_event.set()
                                    while True:
                                        success = lock.acquire(blocking=False)
                                        if success:
                                            try:
                                                self.chatbot.sentence = ""
                                            finally:
                                                lock.release()
                                            break
                                    await self.stop_if_xiaoai_is_playing()
                                    await self.do_tts('')  # 空串施法打断
                                    if not self.chatbot.has_printed:
                                        print()
                                    if query.startswith('闭嘴'):
                                        self.last_timestamp = time_stamp
                                        # 打印彩色信息
                                        print('\033[1;34m' + 'INFO: ' + '\033[0m', end='')
                                        print('\033[1;34m' + 'ChatGPT暂停回答' + '\033[0m')
                                    else:
                                        print('\033[1;34m' + 'INFO: ' + '\033[0m', end='')
                                        print('\033[1;34m' + '有新的问答，ChatGPT停止当前回答' + '\033[0m')
                                    break
                        if self.keep_chat:
                            await miio_command(self.miio_service, self.token_info['mi_did'], '5-4 小爱同学 0')
                    else:
                        try:
                            print(
                                '\032[1;30m' + "小爱同学: " + '\032[0m',
                                last_record.get("answers")[0]
                                .get("tts", {})
                                .get("text"),
                            )
                        except:
                            print("小爱没回")

    async def init_all_data(self, session):
        await self.init_miaccount(session)
        if self.token_info['user_id'] == None or self.token_info['token'] == None or self.token_info['device_id'] == None:
            await self.login()
            self.session = session
        try:
            data = await self.get_latest_ask_from_xiaoai()
        except:
            self.token_info = {"user_id": None, "token": None, "device_id": None, "mi_did": None}
            await self.login()
            self.session = session
            data = await self.get_latest_ask_from_xiaoai()
        self.last_timestamp, self.last_record = self.get_last_timestamp_and_record(data)
        self.chatbot = Chatbot(api_key=self.openai_key, proxy=self.proxy, base_url=self.openai_baseurl)

    # 初始化
    async def init_miaccount(self, session):
        self.account = MiAccount(
            session,
            self.account,
            self.password,
            str(self.mi_token_home),
        )
        self.mina_service = MiNAService(self.account)
        self.miio_service = MiIOService(self.account)

    async def login(self):
        await self.account.login("micoapi")
        await self.set_device_id()
        with open(self.mi_token_home) as f:
            user_data = json.loads(f.read())
        self.token_info['user_id'] = user_data.get("userId")
        self.token_info['token'] = user_data.get("micoapi")[1]
        self.cookie = self.cookie_template.format(
            device_id=self.token_info['device_id'],
            service_token=self.token_info['token'],
            user_id=self.token_info['user_id']
        )
        # 写入json文件
        config = load_json()
        config['token_info'] = self.token_info
        save_json(config)
    # 获取设备ID
    async def set_device_id(self):
        if self.cookie:
            return
        hardware_data = await self.mina_service.device_list()
        for h in hardware_data:
            if h.get("hardware", "") == self.hardware:
                self.token_info['device_id'] = h.get("deviceID")
                self.token_info['mi_did'] = h.get("miotDID")
                break
        else:
            raise Exception(f"we have no hardware: {self.hardware} please check")

    # 设置cookie
    def set_cookie(self):
        token_info = self.token_info
        if self.cookie:
            self.cookie = parse_cookie_string(self.cookie)
        else:
            cookie_string = self.cookie_template.format(
                device_id=token_info['device_id'],
                service_token=token_info['token'],
                user_id=token_info['user_id']
            )
            self.cookie = parse_cookie_string(cookie_string)

    # 获取最近一次对话
    async def get_latest_ask_from_xiaoai(self):
        r = await self.session.get(
            self.last_ask_api.format(
                hardware=self.hardware, timestamp=str(int(time.time() * 1000)),
            ),
            cookies=parse_cookie_string(self.cookie),
            ssl=False
        )
        return await r.json()

    # 获取最近一次对话时间戳和记录
    def get_last_timestamp_and_record(self, data):
        if d := data.get("data"):
            records = json.loads(d).get("records")
            if not records:
                return 0, None
            last_record = records[0]
            timestamp = last_record.get("time")
            return timestamp, last_record

    # 文字转语音
    async def do_tts(self, value):
        if self.use_command:
            await miio_command(self.miio_service, self.token_info['mi_did'], self.tts_command + ' ' + value)
        else:
            try:
                await self.mina_service.text_to_speech(self.token_info['device_id'], value)
            except:
                pass

    async def get_if_xiaoai_is_playing(self):
        playing_info = await self.mina_service.player_get_status(self.token_info['device_id'])
        # WTF xiaomi api
        is_playing = (
            json.loads(playing_info.get("data", {}).get("info", "{}")).get("status", -1)
            == 1
        )
        return is_playing

    async def stop_if_xiaoai_is_playing(self):
        is_playing = await self.get_if_xiaoai_is_playing()
        if is_playing:
            # stop it
            await self.mina_service.player_pause(self.token_info['device_id'])


if __name__ == "__main__":
    CONFIG_PATH = 'config.json'
    options = {
        "token_info": {"user_id": None, "device_id": None, "token": None, "mi_did": None},
        "hardware": "",
        "account": "",
        "password": "",
        "openai_key": "",
        "openai_baseurl": "https://api.openai.com",
        "use_command": False,
        "end_prompt": "请在50字以内回答",
        "keep_chat": False,
        "proxy": None,
    }
    config = load_json()
    for key, value in config.items():
        if key in options:
            options[key] = value
    if not options['openai_key']:
        raise Exception("Use chatgpt api need openai API key, please google how to")
    xiaoGPT = MiGPT(options)
    asyncio.run(xiaoGPT.to_chat())

