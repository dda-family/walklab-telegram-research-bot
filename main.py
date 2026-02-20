import os
import re
import feedparser
import requests
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateparser

# =============================
# 기본 설정
# =============================
MAX_ARTICLES = 10
TIME_WINDOW_HOURS = 48

KST = timezone(timedelta(hours=9))
now_kst = datetime.now(KST)
cutoff_kst = now_kst - timedelta(hours=TIME_WINDOW_HOURS)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in environment variables.")

# =============================
# RSS 목록 (경쟁사 + 트렌드 + 실루엣/자세)
# =============================
RSS_FEEDS = [

    # ===== 경쟁사 =====
    # AIT Studio / MediStep
    'https://news.google.com/rss/search?q=("AIT+Studio"+OR+AIT스튜디오+OR+에이트스튜디오)+(MediStep+OR+메디스텝)+(gait+OR+보행)&hl=ko&gl=KR&ceid=KR:ko',

    # Angel Robotics
    'https://news.google.com/rss/search?q=("Angel+Robotics"+OR+엔젤로보틱스)+("Angel+Legs"+OR+M20)+(gait+OR+rehabilitation)&hl=ko&gl=KR&ceid=KR:ko',

    # WIRobotics
    'https://news.google.com/rss/search?q=("WIRobotics"+OR+위로보틱스)+(gait+OR+웨어러블)&hl=ko&gl=KR&ceid=KR:ko',

    # Spina Systems / PediSol
    'https://news.google.com/rss/search?q=(PediSol+OR+페디솔+OR+"Spina+Systems")+("smart+insole"+OR+족저압)&hl=ko&gl=KR&ceid=KR:ko',

    # Ochy
    'https://news.google.com/rss/search?q=(Ochy)+(gait)&hl=en-US&gl=US&ceid=US:en',

    # ExaMD / LocoStep
    'https://news.google.com/rss/search?q=("LocoStep"+OR+"ExaMD")+(gait)&hl=en-US&gl=US&ceid=US:en',

    # OneStep
    'https://news.google.com/rss/search?q=("OneStep")+(gait+OR+rehabilitation)&hl=en-US&gl=US&ceid=US:en',

    # ===== 기존 트렌드 4축 =====

    # 영상 기반 임상/검증
    'https://news.google.com/rss/search?q=("smartphone+video+gait"+OR+"video+gait+analysis")+(clinical+OR+validation)&hl=en-US&gl=US&ceid=US:en',

    # 보험 / 리스크
    'https://news.google.com/rss/search?q=("gait+digital+biomarker"+OR+"mobility+data")+(insurance+OR+underwriting)&hl=en-US&gl=US&ceid=US:en',

    # 고령자 낙상
    'https://news.google.com/rss/search?q=("fall+prevention"+OR+"fall+risk")+(elderly+OR+seniors)&hl=en-US&gl=US&ceid=US:en',

    # 질환 예측
    'https://news.google.com/rss/search?q=("gait+diabetes"+OR+"gait+Parkinson")+(AI+OR+model)&hl=en-US&gl=US&ceid=US:en',

    # ===== 추가: 자세(실루엣) 1축 =====

    # 영문 실루엣/자세
    'https://news.google.com/rss/search?q=("silhouette+analysis"+OR+"silhouette-based"+OR+"silhouette+score"+OR+clustering)+("posture"+OR+"pose+estimation"+OR+"motion+analysis"+OR+biomechanics)+(gait+OR+rehabilitation+OR+healthcare+OR+clinical)&hl=en-US&gl=US&ceid=US:en',

    # 국문 실루엣/자세
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
    "Ochy", "LocoStep", "ExaMD", "OneStep"
]

TAG_RULES = {
    "💰투자": ["funding", "series", "investment", "raises"],
    "🤝제휴": ["partnership", "collaboration", "mou"],
    "🏥임상": ["clinical", "trial", "fda", "validation", "hospital"],
    "🏛공공": ["government", "city", "public"],
    "🛡보험": ["insurance", "underwriting", "payer"],
    "📱영상기반": ["smartphone", "video", "camera", "markerless"],
    "🧍실루엣": [
        "silhouette analysis", "silhouette-based", "silhouette score",
        "clustering", "cluster analysis",
        "posture", "pose estimation", "biomechanics",
        "실루엣", "자세", "포즈추정", "군집분석"
    ]
}

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

def normalize_title(title):
    return re.sub(r"[^0-9a-zA-Z가-힣]+", "", title).lower()

def parse_published_kst(entry):
    if hasattr(entry, "published"):
        try:
            dt = dateparser.parse(entry.published)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(KST)
        except:
            return None
    return None

def classify_tags(title, summary):
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

def main():
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

            link = getattr(entry, "link", "").strip()
            title = getattr(entry, "title", "").strip()
            summary = getattr(entry, "summary", "")

            if not link or not title:
                continue

            norm_title = normalize_title(title)

            if link in seen_links or norm_title in seen_titles:
                continue

            seen_links.add(link)
            seen_titles.add(norm_title)

            tags = classify_tags(title, summary)
            priority = calc_priority(tags)

            articles.append({
                "title": title,
                "link": link,
                "tags": tags,
                "priority": priority,
                "published_kst": published_kst
            })

    articles.sort(key=lambda x: (x["priority"], x["published_kst"]), reverse=True)
    top = articles[:MAX_ARTICLES]

    if not top:
        send_telegram("📡 오늘 신규 기사 없음 (최근 48시간 기준)")
        return

    msg = "📡 <b>워크랩 리서치 브리핑</b>\n(최근 48시간 / 상위 10건)\n\n"
    for i, a in enumerate(top, 1):
        tag_text = " ".join(a["tags"]) if a["tags"] else ""
        msg += f"{i}. {tag_text}\n<b>{a['title']}</b>\n{a['link']}\n\n"

    send_telegram(msg)

if __name__ == "__main__":
    main()
