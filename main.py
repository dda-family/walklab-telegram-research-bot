import os
import re
import html
import json
import feedparser
import requests
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateparser
from urllib.parse import urlparse, parse_qs

# =============================
# 기본 설정
# =============================
MAX_ARTICLES = 10
TIME_WINDOW_HOURS = 48

# "이미 보낸 기사" 중복 제거 (실행 간 유지)
HISTORY_DAYS = 30
STATE_DIR = ".cache/walklab_radar"
STATE_FILE = os.path.join(STATE_DIR, "state.json")

KST = timezone(timedelta(hours=9))
now_kst = datetime.now(KST)
cutoff_kst = now_kst - timedelta(hours=TIME_WINDOW_HOURS)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in environment variables.")

# =============================
# RSS 목록 (경쟁사 + 트렌드 + 실루엣/자세 + EverEx)
# =============================
RSS_FEEDS = [
    # ===== 경쟁사 =====
    'https://news.google.com/rss/search?q=("AIT+Studio"+OR+AIT스튜디오+OR+에이트스튜디오)+(MediStep+OR+메디스텝)+(gait+OR+보행)&hl=ko&gl=KR&ceid=KR:ko',
    'https://news.google.com/rss/search?q=("Angel+Robotics"+OR+엔젤로보틱스)+("Angel+Legs"+OR+M20)+(gait+OR+rehabilitation)&hl=ko&gl=KR&ceid=KR:ko',
    'https://news.google.com/rss/search?q=("WIRobotics"+OR+위로보틱스)+(gait+OR+웨어러블)&hl=ko&gl=KR&ceid=KR:ko',
    'https://news.google.com/rss/search?q=(PediSol+OR+페디솔+OR+"Spina+Systems")+("smart+insole"+OR+족저압)&hl=ko&gl=KR&ceid=KR:ko',
    'https://news.google.com/rss/search?q=(Ochy)+(gait)&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=("LocoStep"+OR+"ExaMD")+(gait)&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=("OneStep")+(gait+OR+rehabilitation)&hl=en-US&gl=US&ceid=US:en',

    # ===== 추가 경쟁사: EverEx (국문 2 + 영문 2) =====
    'https://news.google.com/rss/search?q=("에버엑스"+OR+"EverEx")+(투자+OR+시리즈+OR+임상+OR+병원+OR+MOU+OR+제휴+OR+보험+OR+수가+OR+디지털치료기기+OR+DTx+OR+과제+OR+해외진출)&hl=ko&gl=KR&ceid=KR:ko',
    'https://news.google.com/rss/search?q=("에버엑스"+OR+"EverEx")+(AI+OR+영상+OR+비전+OR+분석+OR+운동코칭+OR+재활플랫폼+OR+자세+OR+실루엣+OR+군집)&hl=ko&gl=KR&ceid=KR:ko',
    'https://news.google.com/rss/search?q=("EverEx")+(funding+OR+investment+OR+clinical+OR+hospital+OR+insurance+OR+DTx+OR+expansion+OR+partnership)&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=("EverEx")+("digital+rehabilitation"+OR+"AI+therapy"+OR+"motion+analysis"+OR+"pose+estimation"+OR+"exercise+platform")&hl=en-US&gl=US&ceid=US:en',

    # ===== 트렌드 4축 =====
    'https://news.google.com/rss/search?q=("smartphone+video+gait"+OR+"video+gait+analysis")+(clinical+OR+validation)&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=("gait+digital+biomarker"+OR+"mobility+data")+(insurance+OR+underwriting)&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=("fall+prevention"+OR+"fall+risk")+(elderly+OR+seniors)&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=("gait+diabetes"+OR+"gait+Parkinson")+(AI+OR+model)&hl=en-US&gl=US&ceid=US:en',

    # ===== 추가: 자세(실루엣) 1축(영/국문 포함) =====
    'https://news.google.com/rss/search?q=("silhouette+analysis"+OR+"silhouette-based"+OR+"silhouette+score"+OR+clustering)+("posture"+OR+"pose+estimation"+OR+"motion+analysis"+OR+biomechanics)+(gait+OR+rehabilitation+OR+healthcare+OR+clinical)&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=(실루엣+OR+자세+OR+포즈추정+OR+군집분석)+(보행+OR+재활+OR+헬스케어+OR+의료)+-패션+-의류+-사진&hl=ko&gl=KR&ceid=KR:ko',
]

# =============================
# 태그 분류
# =============================
COMPANY_KEYWORDS = [
    "AIT Studio", "AIT스튜디오", "에이트스튜디오", "MediStep", "메디스텝",
    "Angel Robotics", "엔젤로보틱스", "Angel Legs", "M20",
    "WIRobotics", "위로보틱스",
    "Spina Systems", "스피나시스템즈", "PediSol", "페디솔",
    "Ochy", "LocoStep", "ExaMD", "OneStep",
    "EverEx", "에버엑스"
]

TAG_RULES = {
    "💰투자": ["funding", "series", "investment", "raises", "투자", "시리즈"],
    "🤝제휴": ["partnership", "collaboration", "mou", "제휴", "협약", "mou"],
    "🏥임상": ["clinical", "trial", "fda", "validation", "hospital", "임상", "병원"],
    "🏛공공": ["government", "city", "public", "정부", "지자체", "공공"],
    "🛡보험": ["insurance", "underwriting", "payer", "보험", "수가"],
    "📱영상기반": ["smartphone", "video", "camera", "markerless", "영상", "비전", "카메라"],
    "🧍실루엣": [
        "silhouette analysis", "silhouette-based", "silhouette score",
        "clustering", "cluster analysis",
        "posture", "pose estimation", "biomechanics",
        "실루엣", "자세", "포즈추정", "군집분석"
    ]
}

# =============================
# 유틸
# =============================
def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    r = requests.post(url, data=payload, timeout=20)
    r.raise_for_status()

def normalize_title(title: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]+", "", title).lower()

def parse_published_kst(entry):
    if hasattr(entry, "published"):
        try:
            dt = dateparser.parse(entry.published)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(KST)
        except Exception:
            return None
    return None

def classify_tags(title: str, summary: str):
    text = (title + " " + summary).lower()
    tags = []

    for kw in COMPANY_KEYWORDS:
        if kw.lower() in text:
            tags.append("🏢경쟁사")
            break

    for tag, kws in TAG_RULES.items():
        for k in kws:
            if k.lower() in text:
                tags.append(tag)
                break

    return tags

def calc_priority(tags):
    score = 0
    if "🏢경쟁사" in tags:
        score += 100
    if "💰투자" in tags:
        score += 30
    if "🏥임상" in tags:
        score += 30
    if "🤝제휴" in tags:
        score += 20
    if "🛡보험" in tags:
        score += 15
    if "🏛공공" in tags:
        score += 15
    if "🧍실루엣" in tags:
        score += 10
    if "📱영상기반" in tags:
        score += 8
    return score

def extract_original_url(url: str) -> str:
    """
    Google News RSS 링크에 url= 파라미터가 있으면 원문 URL로 바꿉니다.
    (없으면 그대로 반환)
    """
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "url" in qs and qs["url"]:
            return qs["url"][0]
    except Exception:
        pass
    return url

def format_item(i: int, tags, title: str, link: str) -> str:
    safe_title = html.escape(title)
    safe_link = html.escape(link)
    tag_text = " ".join(tags) if tags else ""
    return f"{i}. {tag_text}\n<a href=\"{safe_link}\">{safe_title}</a>\n"

# =============================
# 상태(히스토리) 저장/로드: 30일
# =============================
def load_state():
    os.makedirs(STATE_DIR, exist_ok=True)
    if not os.path.exists(STATE_FILE):
        return {"sent": []}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "sent" not in data or not isinstance(data["sent"], list):
            return {"sent": []}
        return data
    except Exception:
        return {"sent": []}

def prune_state(state):
    keep_after = now_kst - timedelta(days=HISTORY_DAYS)
    pruned = []
    for item in state.get("sent", []):
        try:
            ts = dateparser.parse(item.get("sent_at"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts_kst = ts.astimezone(KST)
            if ts_kst >= keep_after:
                pruned.append(item)
        except Exception:
            # 파싱 실패 항목은 버림
            continue
    state["sent"] = pruned
    return state

def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def build_history_sets(state):
    url_set = set()
    title_set = set()
    for item in state.get("sent", []):
        u = (item.get("url") or "").strip()
        t = (item.get("title_norm") or "").strip()
        if u:
            url_set.add(u)
        if t:
            title_set.add(t)
    return url_set, title_set

# =============================
# 메인
# =============================
def main():
    # 히스토리 로드 + 30일 프루닝
    state = prune_state(load_state())
    sent_url_set, sent_title_set = build_history_sets(state)

    articles = []
    seen_links = set()
    seen_titles = set()

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)

        for entry in getattr(feed, "entries", []):
            published_kst = parse_published_kst(entry)
            if not published_kst:
                continue
            if published_kst < cutoff_kst:
                continue

            raw_link = getattr(entry, "link", "").strip()
            title = getattr(entry, "title", "").strip()
            summary = getattr(entry, "summary", "")

            if not raw_link or not title:
                continue

            # 원문 링크로 정규화(중복 판단의 핵심)
            link = extract_original_url(raw_link).strip()
            norm_title = normalize_title(title)

            # (실행 내부) 중복 제거
            if link in seen_links or norm_title in seen_titles:
                continue

            # (실행 간) 이미 보낸 기사 필터: URL + 제목(정규화) 기준
            if link in sent_url_set or norm_title in sent_title_set:
                continue

            seen_links.add(link)
            seen_titles.add(norm_title)

            tags = classify_tags(title, summary)
            priority = calc_priority(tags)

            articles.append({
                "title": title,
                "title_norm": norm_title,
                "link": link,
                "tags": tags,
                "priority": priority,
                "published_kst": published_kst
            })

    # 우선순위/최신순 정렬 후 상위 10건
    articles.sort(key=lambda x: (x["priority"], x["published_kst"]), reverse=True)
    top = articles[:MAX_ARTICLES]

    if not top:
        send_telegram("📡 신규 기사 없음 (최근 48시간 / 중복 제외)")
        # 프루닝 결과는 저장(파일 손상 대비)
        save_state(state)
        return

    # 구역 분리(상위 10건 안에서만)
    competitors = [a for a in top if "🏢경쟁사" in a["tags"]]
    trends = [a for a in top if "🏢경쟁사" not in a["tags"]]

    competitors.sort(key=lambda x: (x["priority"], x["published_kst"]), reverse=True)
    trends.sort(key=lambda x: (x["priority"], x["published_kst"]), reverse=True)

    msg = "📡 <b>워크랩 리서치 브리핑</b>\n(최근 48시간 / 중복 제외 / 상위 10건)\n\n"

    if competitors:
        msg += "━━━━━━━━━━\n<b>🏢 경쟁사 흐름</b>\n━━━━━━━━━━\n"
        for i, a in enumerate(competitors, 1):
            msg += format_item(i, a["tags"], a["title"], a["link"]) + "\n"

    if trends:
        msg += "━━━━━━━━━━\n<b>📈 기술 트렌드</b>\n━━━━━━━━━━\n"
        for i, a in enumerate(trends, 1):
            msg += format_item(i, a["tags"], a["title"], a["link"]) + "\n"

    # 전송
    send_telegram(msg)

    # 전송 성공한 항목들을 히스토리에 기록 (30일 유지)
    sent_at = now_kst.isoformat()
    for a in top:
        state["sent"].append({
            "url": a["link"],
            "title_norm": a["title_norm"],
            "sent_at": sent_at
        })

    # 저장 (actions/cache가 다음 실행에 복원)
    save_state(state)

if __name__ == "__main__":
    main()
