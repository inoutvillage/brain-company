"""画面に出す文から、よくある形の鍵・合言葉を伏せる（当たらない形の鍵は伏せられない。見本の一覧であって、守りの全部ではない）"""
import re

SECRET_RES = [
    # 秘密鍵は終わりの印まで。終わりの印が無い（途中で切れた）時は、続く鍵の文字を全部
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----|[A-Za-z0-9+/=\s]*)"), "<伏せた>"),
    (re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"), "<伏せた>"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}"), "<伏せた>"),
    (re.compile(r"\bgithub[_]pat_[A-Za-z0-9_]{30,}"), "<伏せた>"),  # [_] は、この行そのものが鍵と見なされないため
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"), "<伏せた>"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<伏せた>"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "<伏せた>"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "<伏せた>"),
    (re.compile(r"\bvercel_blob_rw_[A-Za-z0-9_]{10,}"), "<伏せた>"),
    (re.compile(r"Bearer\s+\S+"), "Bearer <伏せた>"),
    # 名前に KEY・SECRET・TOKEN・PASSWORD などを含む値（API_KEY=… や "apiKey": "…" も）
    (re.compile(r"\b([A-Za-z0-9_]*(?:api[_-]?key|secret|password|passwd|passphrase|token|access[_-]?key|private[_-]?key|credential)[A-Za-z0-9_]*[\"']?\s*[:=]\s*[\"']?)[^\s\"',;]{8,}", re.I), r"\1<伏せた>"),
    # 知っているだけで送れてしまう URL（Slack・Discord の受け口、Vercel のデプロイフック）
    (re.compile(r"https://hooks\.slack\.com/services/[^\s\"'<>)]+"), "<伏せた URL>"),
    (re.compile(r"https://(?:discord|discordapp)\.com/api/webhooks/[^\s\"'<>)]+"), "<伏せた URL>"),
    (re.compile(r"https://api\.vercel\.com/v1/integrations/deploy/[^\s\"'<>)]+"), "<伏せた URL>"),
]


def mask_secrets(text: str) -> str:
    return mask_count(text)[0]


def mask_count(text: str) -> tuple[str, int]:
    """伏せた文と、伏せた数"""
    total = 0
    for rx, to in SECRET_RES:
        text, n = rx.subn(to, text)
        total += n
    return text, total
