#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
假 TR-069 ACS —— 用来跟 Singtel mesh 说话

背景：设备每 45 秒主动去连 https://bs-hdm.singnet.com.sg/cwmpWeb/CPEMgt，
      而那个域名早死了（DNS 已劫持到本机）。它一连上来，我就接住。

TR-069 (CWMP) 的对话流程：
    CPE  --POST Inform-->            ACS
    CPE  <--InformResponse--         ACS
    CPE  --POST (空)-->              ACS
    CPE  <--GetParameterNames/SetParameterValues--  ACS   ← ★ 这里我能下发命令
    CPE  --POST (响应)-->            ACS
    CPE  <--(空)-->                  ACS   → 会话结束

第一阶段目标（只读，不改任何东西）：
    把设备报上来的参数、以及它的完整数据模型 (GetParameterNames) 抓下来。

用法：
    sudo python3 acs.py                 # 监听 443，所有请求记到 acs.log
"""
import json
import os
import re
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "acs.log")
BODIES = os.path.join(HERE, "bodies")
CERT = os.path.join(HERE, "acs.crt")
KEY = os.path.join(HERE, "acs.key")

# 已完成的会话计数（用来决定第二次空 POST 时发什么）
seen = {}
lock = threading.Lock()


def log(*a):
    line = time.strftime("[%H:%M:%S] ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def action_of(body, headers):
    """从 SOAPAction 头或正文里认出这是什么消息"""
    sa = headers.get("SOAPAction") or headers.get("Soapaction") or ""
    m = re.search(r"#([A-Za-z]+)", sa)
    if m:
        return m.group(1)
    for name in ("Inform", "GetParameterValuesResponse", "SetParameterValuesResponse",
                 "GetParameterNamesResponse", "TransferComplete", "Fault",
                 "DownloadResponse", "RebootResponse"):
        if f":{name}" in body or f"<{name}" in body:
            return name
    return "Empty" if not body.strip() else "Unknown"


def inform_response():
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<soap-env:Envelope xmlns:soap-env="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:soap-enc="http://schemas.xmlsoap.org/soap/encoding/" '
            'xmlns:cwmp="urn:dslforum-org:cwmp-1-0">'
            "<soap-env:Header><cwmp:ID soap-env:mustUnderstand=\"1\">1</cwmp:ID></soap-env:Header>"
            "<soap-env:Body><cwmp:InformResponse><MaxEnvelopes>1</MaxEnvelopes>"
            "</cwmp:InformResponse></soap-env:Body></soap-env:Envelope>")


def get_parameter_names(path="InternetGatewayDevice."):
    """让设备把它的参数树报上来 —— 这是摸清它暴露了什么的关键"""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<soap-env:Envelope xmlns:soap-env="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:soap-enc="http://schemas.xmlsoap.org/soap/encoding/" '
            'xmlns:cwmp="urn:dslforum-org:cwmp-1-0">'
            "<soap-env:Header><cwmp:ID soap-env:mustUnderstand=\"1\">2</cwmp:ID></soap-env:Header>"
            "<soap-env:Body><cwmp:GetParameterNames>"
            f"<ParameterPath>{path}</ParameterPath><NextLevel>0</NextLevel>"
            "</cwmp:GetParameterNames></soap-env:Body></soap-env:Envelope>")


TASK = os.path.join(HERE, "task.json")


def load_task():
    """task.json 里写要下发的参数：{"set": {"参数名": "值", ...}}

    没有这个文件时，ACS 只做侦察（GetParameterNames），不改任何东西。
    """
    if not os.path.exists(TASK):
        return None
    try:
        return json.load(open(TASK))
    except Exception as e:
        log("task.json 解析失败:", e)
        return None


def set_parameter_values(pairs):
    items = "".join(
        "<ParameterValueStruct>"
        f"<Name>{k}</Name><Value xsi:type=\"xsd:string\">{v}</Value>"
        "</ParameterValueStruct>"
        for k, v in pairs.items())
    log(f"    ★ 下发 SetParameterValues: {pairs}")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<soap-env:Envelope xmlns:soap-env="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:soap-enc="http://schemas.xmlsoap.org/soap/encoding/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:cwmp="urn:dslforum-org:cwmp-1-0">'
            "<soap-env:Header><cwmp:ID soap-env:mustUnderstand=\"1\">3</cwmp:ID></soap-env:Header>"
            "<soap-env:Body><cwmp:SetParameterValues>"
            f"<ParameterList soap-enc:arrayType=\"cwmp:ParameterValueStruct[{len(pairs)}]\">"
            f"{items}</ParameterList><ParameterKey></ParameterKey>"
            "</cwmp:SetParameterValues></soap-env:Body></soap-env:Envelope>")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _read(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n).decode("utf-8", "replace") if n else ""

    def do_POST(self):
        body = self._read()
        act = action_of(body, self.headers)
        peer = self.client_address[0]
        with lock:
            seen[peer] = seen.get(peer, 0) + 1
            n = seen[peer]

        os.makedirs(BODIES, exist_ok=True)
        fn = os.path.join(BODIES, f"{int(time.time())}_{peer.replace('.','_')}_{n}_{act}.xml")
        open(fn, "w").write(body)
        log(f"POST {self.path}  from {peer}  #{n}  action={act}  {len(body)}B -> {os.path.basename(fn)}")

        if act == "Inform":
            # 把 Inform 里的关键信息抠出来
            for tag in ("Manufacturer", "OUI", "ProductClass", "SerialNumber",
                        "HardwareVersion", "SoftwareVersion", "ConnectionRequestURL",
                        "ParameterKey", "Event"):
                m = re.search(rf"<{tag}[^>]*>([^<]*)</{tag}>", body)
                if m:
                    log(f"    {tag} = {m.group(1)}")
            for ev in re.findall(r"<EventCode>([^<]*)</EventCode>", body):
                log(f"    EventCode = {ev}")
            payload = inform_response()

        elif act == "Empty":
            task = load_task()
            if n <= 2 and task and task.get("set"):
                payload = set_parameter_values(task["set"])
            elif n <= 2:
                # 没有 task.json → 只做侦察，不改任何东西
                log("    → 回 GetParameterNames(InternetGatewayDevice.) 做侦察")
                log("      （想下发配置就往 ~/acs/task.json 写 {\"set\":{...}}）")
                payload = get_parameter_names()
            else:
                payload = ""      # 结束会话

        elif act == "SetParameterValuesResponse":
            st = re.search(r"<Status>([^<]*)</Status>", body)
            log(f"    ★★ SetParameterValues 结果 = {st.group(1) if st else '?'}  (1=成功 0=失败)")
            payload = ""
        elif act == "GetParameterNamesResponse":
            paths = re.findall(r"<Name>([^<]*)</Name>", body)
            log(f"    ★ 参数树回来 {len(paths)} 条，存 param_names.txt")
            open(os.path.join(HERE, "param_names.txt"), "a").write("\n".join(paths) + "\n")
            payload = ""
        else:
            payload = ""

        data = payload.encode()
        self.send_response(200)
        self.send_header("Content-Type", 'text/xml; charset="utf-8"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        if data:
            self.wfile.write(data)

    def do_GET(self):
        log(f"GET {self.path} from {self.client_address[0]}")
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def main():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    srv = ThreadingHTTPServer(("0.0.0.0", 443), Handler)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    log("=" * 60)
    log("假 ACS 启动，监听 0.0.0.0:443（HTTPS，自签证书）")
    log("等设备来连...  日志:", LOG)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("停止")


if __name__ == "__main__":
    main()
