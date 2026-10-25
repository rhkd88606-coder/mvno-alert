# -*- coding: utf-8 -*-
"""
알뜰폰 마이너 갤러리(디시인사이드)에 새 글이 올라오면 확인해서,
좋은 요금제로 보이는 글이면 디스코드로 알림을 보내는 프로그램.

어떤 글을 알려주나?
  0) 말머리가 '행사'인 글은 무조건
  1) 말머리나 제목에 '굴비', '전설', '대란' 이 들어간 글
  2) 제목만 봐도 아래 조건에 맞아 보이는 글
     A. 통화·문자 무제한 + 평생 요금제 + 월 770원 이하
     B. eSIM(이심) 데이터용 + 5G + 30GB 이상 + 월 100원 이하
     C. 평생 요금제 + 월 110원 이하, 또는 '실 청구 0원'
"""
import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

GALLERY_ID = "mvnogallery"
LIST_URL = "https://gall.dcinside.com/mgallery/board/lists/"
VIEW_URL = "https://gall.dcinside.com/mgallery/board/view/?id={gid}&no={no}"
MOBILE_URL = "https://m.dcinside.com/board/{gid}/{no}"
PAGES_TO_CHECK = 3  # 한 페이지에 글 50개, 최신 3페이지(150개)를 확인
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}

GRADE_WORDS = ["굴비", "전설", "대란"]
ALWAYS_HEADS = ["행사"]  # 이 말머리 글은 무조건 알림


# ---------------------------------------------------------------- 글 목록 읽기
def fetch_posts():
    posts = {}
    for page in range(1, PAGES_TO_CHECK + 1):
        resp = requests.get(
            LIST_URL,
            params={"id": GALLERY_ID, "page": page},
            headers=HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        for post in parse_list(resp.text):
            posts[post["no"]] = post
        time.sleep(1)
    return sorted(posts.values(), key=lambda p: p["no"])


def parse_list(html):
    soup = BeautifulSoup(html, "html.parser")
    result = []
    for tr in soup.select("tr.ub-content"):
        num = tr.select_one("td.gall_num")
        if not num or not num.get_text(strip=True).isdigit():
            continue  # 공지, 광고 등은 건너뜀
        title_a = tr.select_one("td.gall_tit a")
        if not title_a:
            continue
        head = tr.select_one("td.gall_subject")
        result.append({
            "no": int(num.get_text(strip=True)),
            "head": head.get_text(strip=True) if head else "",
            "title": title_a.get_text(" ", strip=True),
        })
    return result


# ---------------------------------------------------------------- 좋은 글 판단
def prices_won(text):
    """'770원', '1,100원', '0원' 같은 금액을 숫자로 뽑아냄."""
    return [int(m.replace(",", "")) for m in re.findall(r"(\d[\d,]*)\s*원", text)]


def data_gb(text):
    """'30GB', '30기가', '100G' 같은 데이터 양을 숫자로 뽑아냄."""
    return [int(m) for m in re.findall(r"(\d+)\s*(?:gb|기가|g)(?![a-z])", text.lower())]


def judge(post):
    """알릴 이유 목록을 돌려줌. 빈 목록이면 알리지 않음."""
    text = f"{post['head']} {post['title']}"
    low = text.lower().replace(" ", "")
    reasons = []

    if post["head"] in ALWAYS_HEADS:
        reasons.append(f"말머리 '{post['head']}' 글")

    for word in GRADE_WORDS:
        if word in text:
            reasons.append(f"'{word}' 표시가 있는 글")
            break

    prices = prices_won(text)
    cheapest = min(prices) if prices else None

    unlimited = "무제한" in low or "무한" in low
    lifetime = "평생" in low
    if unlimited and lifetime and cheapest is not None and cheapest <= 770:
        reasons.append(f"조건 A: 평생·무제한·{cheapest}원 (770원 이하)")

    # 전설급처럼 아주 싼 평생 요금제 (통화 분량은 상관없음)
    if lifetime and cheapest is not None and cheapest <= 110:
        reasons.append(f"조건 C: 평생·{cheapest}원 (110원 이하)")
    elif re.search(r"실(?:청구|납부|부담)(?:금액|액)?0원", low):
        reasons.append("조건 C: 실 청구 0원")

    esim = "esim" in low or "이심" in low
    is_5g = "5g" in low
    big_data = [g for g in data_gb(text) if g >= 30]
    if (esim or is_5g) and big_data and cheapest is not None and cheapest <= 100:
        reasons.append(f"조건 B: 데이터 {max(big_data)}GB·{cheapest}원 (100원 이하)")

    return reasons


# ---------------------------------------------------------------- 디스코드 알림
def send_discord(post, reasons):
    url = VIEW_URL.format(gid=GALLERY_ID, no=post["no"])
    mobile_url = MOBILE_URL.format(gid=GALLERY_ID, no=post["no"])
    head = f"[{post['head']}] " if post["head"] else ""
    message = {
        "content": (
            f"📢 **좋은 요금제 글 발견!**\n"
            f"**{head}{post['title']}**\n"
            f"이유: {', '.join(reasons)}\n"
            f"\n"
            f"📱 휴대폰으로 보기: {mobile_url}\n"
            f"💻 컴퓨터로 보기: {url}"
        ),
        "allowed_mentions": {"parse": []},
    }
    if not WEBHOOK_URL:
        print("[웹훅 없음, 화면에만 출력]", message["content"])
        return
    r = requests.post(WEBHOOK_URL, json=message, timeout=20)
    if r.status_code == 429:  # 너무 빨리 보내면 잠깐 쉬고 다시
        time.sleep(float(r.json().get("retry_after", 2)))
        r = requests.post(WEBHOOK_URL, json=message, timeout=20)
    r.raise_for_status()
    time.sleep(1)


# ---------------------------------------------------------------- 기억(마지막으로 본 글 번호)
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def main():
    if "--test" in sys.argv:
        send_discord({"no": 0, "head": "테스트", "title": "알림이 잘 오는지 확인하는 테스트 메시지예요"},
                     ["연결 테스트"])
        print("테스트 메시지를 보냈어요.")
        return

    state = load_state()
    last_no = state.get("last_no")
    posts = fetch_posts()
    if not posts:
        print("글 목록을 못 읽었어요. 사이트 구조가 바뀌었을 수 있어요.")
        sys.exit(1)

    if last_no is None:
        # 처음 실행: 옛날 글로 알림 폭탄이 오지 않도록, 지금 글 번호만 기억
        print(f"첫 실행이라 기준만 저장해요. 최신 글 번호: {posts[-1]['no']}")
    else:
        new_posts = [p for p in posts if p["no"] > last_no]
        print(f"새 글 {len(new_posts)}개 확인")
        for post in new_posts:
            reasons = judge(post)
            if reasons:
                print("알림:", post["no"], post["title"], reasons)
                send_discord(post, reasons)

    state["last_no"] = max(posts[-1]["no"], last_no or 0)
    save_state(state)


if __name__ == "__main__":
    main()
