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

# 실행 간 중복 제거(히스토리 유지)
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
# RSS 목록
# =============================
WEEKLY_FUNDING_FEED = 'https://news.google.com/rss/search?q=site:unicornfactory.co.kr+"[이주의+투자유치]"&hl=ko&gl=KR&ceid=KR:ko'

RSS_FEEDS = [
    # ===== 경쟁사 =====
    'https://news.google.com/rss/search?q=("AIT+Studio"+OR+AIT스튜디오+OR+에이트스튜디오)+(MediStep+OR+메디스텝)+(gait+OR+보행)&hl=ko&gl=KR&ceid=KR:ko',
    'https://news.google.com/rss/search?q=("Angel+Robotics"+OR+엔젤로보틱스)+("Angel+Legs"+OR+M20)+(gait+OR+rehabilitation)&hl=ko&gl=KR&ceid=KR:ko',
    'https://news.google.com/rss/search?q=("WIRobotics"+OR+위로보틱스)+(gait+OR+웨어러블)&hl=ko&gl=KR&ceid=KR:ko',
    'https://news.google.com/rss/search?q=(PediSol+OR+페디솔+OR+"Spina+Systems")+("smart+insole"+OR+족저압)&hl=ko&gl=KR&ceid=KR:ko',
    'https://news.google.com/rss/search?q=(Ochy)+(gait)&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=("LocoStep"+OR+"ExaMD")+(gait)&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=("OneStep")+(gait+OR+rehabilitation)&hl=en-US&gl=US&ceid=US:en',

    # ===== 추가 경쟁사: EverEx =====
    'https://news.google.com/rss/search?q=("에버엑스"+OR+"EverEx")+(투자+OR+시리즈+OR+임상+OR+병원+OR+MOU+OR+제휴+OR+보험+OR+수가+OR+디지털치료기기+OR+DTx+OR+과제+OR+해외진출)&hl=ko&gl=KR&ceid=KR:ko',
    'https://news.google.com/rss/search?q=("에버엑스"+OR+"EverEx")+(AI+OR+영상+OR+비전+OR+분석+OR+운동코칭+OR+재활플랫폼+OR+자세+OR+실루엣+OR+군집)&hl=ko&gl=KR&ceid=KR:ko',
    'https://news.google.com/rss/search?q=("EverEx")+(funding+OR+investment+OR+clinical+OR+hospital+OR+insurance+OR+DTx+OR+expansion+OR+partnership)&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=("EverEx")+("digital+rehabilitation"+OR+"AI+therapy"+OR+"motion+analysis"+OR+"pose+estimation"+OR+"exercise+platform")&hl=en-US&gl=US&ceid=US:en',

    # ===== 기술 트렌드 =====
    'https://news.google.com/rss/search?q=("smartphone+video+gait"+OR+"video+gait+analysis")+(clinical+OR+validation)&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=("gait+digital+biomarker"+OR+"mobility+data")+(insurance+OR+underwriting)&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=("fall+prevention"+OR+"fall+risk")+(elderly+OR+seniors)&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=("gait+diabetes"+OR+"gait+Parkinson")+(AI+OR+model)&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=("silhouette+analysis"+OR+"silhouette-based"+OR+"silhouette+score"+OR+clustering)+("posture"+OR+"pose+estimation"+OR+"motion+analysis"+OR+"biomechanics")+(gait+OR+rehabilitation+OR+healthcare+OR+clinical)&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=(실루엣+OR+자세+OR+포즈추정+OR+군집분석)+(보행+OR+재활+OR+헬스케어+OR+의료)+-패션+-의류+-사진&hl=ko&gl=KR&ceid=KR:ko',

    # ===== 이주의 투자유치 (전용) =====
    WEEKLY_FUNDING_FEED,
]

# =============================
# 경쟁사(회사명) 감지 키워드
# =============================
COMPANY_KEYWORDS = [
    "EverEx", "에버엑스",
    "AIT Studio", "AIT스튜디오", "에이트스튜디오",
    "MediStep", "메디스텝",
    "Angel Robotics", "엔젤로보틱스", "Angel Legs", "M20",
    "WIRobotics", "위로보틱스",
    "Spina Systems", "스피나시스템즈",
    "PediSol", "페디솔",
    "Ochy",
    "LocoStep", "ExaMD",
    "OneStep",
]

COMPANY_CANONICAL = {
    "에버엑스": "EverEx",
    "everex": "EverEx",

    "ait studio": "AIT Studio",
    "ait스튜디오": "AIT Studio",
    "에이트스튜디오": "AIT Studio",

    "medistep": "MediStep",
    "메디스텝": "MediStep",

    "angel robotics": "Angel Robotics",
    "엔젤로보틱스": "Angel Robotics",
    "angel legs": "Angel Robotics",
    "m20": "Angel Robotics",

    "wirobotics": "WIRobotics",
    "위로보틱스": "WIRobotics",

    "spina systems": "Spina Systems",
    "스피나시스템즈": "Spina Systems",

    "pedisol": "PediSol",
    "페디솔": "PediSol",

    "ochy": "Ochy",

    "locostep": "LocoStep",
    "examd": "ExaMD",

    "onestep": "OneStep",
}

# =============================
# 태그 규칙
# =============================
TAG_RULES = {
    # 전략/사업 신호
    "💰투자": ["funding", "series", "investment", "raises", "seed", "pre-seed", "round", "투자", "시리즈", "유치"],
    "🤝제휴": ["partnership", "collaboration", "mou", "alliance", "제휴", "협약", "업무협약", "파트너십"],
    "🏥임상": ["clinical", "trial", "validation", "hospital", "fda", "ce mark", "임상", "병원", "검증", "시험"],
    "🏛공공": ["government", "city", "public", "municipal", "정부", "지자체", "공공"],
    "🛡보험": ["insurance", "underwriting", "payer", "reimbursement", "cpt", "보험", "수가", "언더라이팅"],

    # 기술 축
    "📱영상기반": ["smartphone", "video", "camera", "vision", "markerless", "pose estimation", "영상", "비전", "카메라", "포즈"],
    "🧍실루엣": [
        "silhouette analysis", "silhouette-based", "silhouette score",
        "clustering", "cluster analysis",
        "posture", "biomechanics",
        "실루엣", "자세", "군집분석", "체형"
    ],
    "🧠AI": ["ai", "ml", "deep learning", "neural", "model", "machine learning", "인공지능", "딥러닝", "머신러닝", "모델"],
    "🏃운동/재활": ["rehab", "rehabilitation", "therapy", "exercise", "coaching", "physio", "재활", "운동", "코칭", "치료"],
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
    r = requests.post(url, data=payload, timeout=25)
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

def extract_original_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "url" in qs and qs["url"]:
            return qs["url"][0]
    except Exception:
        pass
    return url

def strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def truncate_snippet(text: str, limit: int = 200) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."

def detect_company(title: str, summary: str):
    blob = (title + " " + summary).lower()
    for kw in COMPANY_KEYWORDS:
        if kw.lower() in blob:
            canon = COMPANY_CANONICAL.get(kw.lower(), kw)
            return True, canon
    for raw, canon in COMPANY_CANONICAL.items():
        if raw in blob:
            return True, canon
    return False, None

def classify_tags(title: str, summary: str):
    text = (title + " " + summary).lower()
    tags = []
    for tag, kws in TAG_RULES.items():
        for k in kws:
            if k.lower() in text:
                tags.append(tag)
                break
    return tags

def calc_priority(is_competitor: bool, tags):
    score = 0
    if is_competitor:
        score += 100

    if "💰투자" in tags:
        score += 30
    if "🏥임상" in tags:
        score += 25
    if "🤝제휴" in tags:
        score += 18
    if "🛡보험" in tags:
        score += 15
    if "🏛공공" in tags:
        score += 12

    if "🧍실루엣" in tags:
        score += 10
    if "📱영상기반" in tags:
        score += 8
    if "🧠AI" in tags:
        score += 6
    if "🏃운동/재활" in tags:
        score += 6

    return score

def format_tags(tags):
    return " · ".join(tags) if tags else ""

def format_competitor_line(idx: int, company: str, tags):
    tag_text = format_tags(tags)
    if tag_text:
        return f'{idx}. <b>[{html.escape(company)}]</b> · {html.escape(tag_text)}'
    return f'{idx}. <b>[{html.escape(company)}]</b>'

def format_trend_line(idx: int, tags):
    tag_text = format_tags(tags)
    return f'{idx}. {html.escape(tag_text)}' if tag_text else f'{idx}.'

def format_title_link(title: str, link: str) -> str:
    safe_title = html.escape(title)
    safe_link = html.escape(link)
    return f'<b><a href="{safe_link}">{safe_title}</a></b>'

def extract_week_label(title: str, summary: str) -> str | None:
    text = f"{title} {summary}"
    m = re.search(r'(\d{1,2})월\s*(첫째|둘째|셋째|넷째|다섯째)주', text)
    if m:
        month = int(m.group(1))
        nth = m.group(2)
        return f"{month}월 {nth}"
    return None

def build_week_key(published_kst: datetime, week_label: str | None) -> str | None:
    if not week_label:
        return None
    return f"{published_kst.year}-{week_label}"

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
    weekly_key_set = set()

    for item in state.get("sent", []):
        u = (item.get("url") or "").strip()
        t = (item.get("title_norm") or "").strip()
        wk = (item.get("weekly_key") or "").strip()

        if u:
            url_set.add(u)
        if t:
            title_set.add(t)
        if wk:
            weekly_key_set.add(wk)

    return url_set, title_set, weekly_key_set

# =============================
# 메인
# =============================
def main():
    state = prune_state(load_state())
    sent_url_set, sent_title_set, sent_weekly_key_set = build_history_sets(state)

    regular_articles = []
    weekly_funding_articles = []

    seen_links = set()
    seen_titles = set()
    seen_weekly_keys = set()

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
            raw_summary = getattr(entry, "summary", "") or ""

            if not raw_link or not title:
                continue

            link = extract_original_url(raw_link).strip()
            norm_title = normalize_title(title)
            clean_summary = strip_html(raw_summary)
            snippet = truncate_snippet(clean_summary, 200)

            # ===== 이주의 투자유치: 전용 RSS에서 온 기사만 분류 =====
            if feed_url == WEEKLY_FUNDING_FEED:
                week_label = extract_week_label(title, clean_summary)
                weekly_key = build_week_key(published_kst, week_label)

                # 실행 내부 중복
                if link in seen_links or norm_title in seen_titles:
                    continue
                if weekly_key and weekly_key in seen_weekly_keys:
                    continue

                # 실행 간 중복
                if link in sent_url_set or norm_title in sent_title_set:
                    continue
                if weekly_key and weekly_key in sent_weekly_key_set:
                    continue

                seen_links.add(link)
                seen_titles.add(norm_title)
                if weekly_key:
                    seen_weekly_keys.add(weekly_key)

                weekly_funding_articles.append({
                    "title": title,
                    "title_norm": norm_title,
                    "link": link,
                    "snippet": snippet,
                    "week_label": week_label or "이주의 투자유치",
                    "weekly_key": weekly_key or "",
                    "published_kst": published_kst,
                })
                continue

            # ===== 일반 기사 =====
            if link in seen_links or norm_title in seen_titles:
                continue

            if link in sent_url_set or norm_title in sent_title_set:
                continue

            seen_links.add(link)
            seen_titles.add(norm_title)

            is_competitor, company = detect_company(title, clean_summary)
            tags = classify_tags(title, clean_summary)

            tag_order = ["💰투자", "🏥임상", "🤝제휴", "🛡보험", "🏛공공", "🧍실루엣", "📱영상기반", "🧠AI", "🏃운동/재활"]
            tags_sorted = [t for t in tag_order if t in tags]
            tags_display = tags_sorted[:4]

            priority = calc_priority(is_competitor, tags)

            regular_articles.append({
                "title": title,
                "title_norm": norm_title,
                "link": link,
                "snippet": snippet,
                "is_competitor": is_competitor,
                "company": company,
                "tags": tags_display,
                "priority": priority,
                "published_kst": published_kst
            })

    # 경쟁사/기술 트렌드는 상위 10건
    regular_articles.sort(key=lambda x: (x["priority"], x["published_kst"]), reverse=True)
    top_regular = regular_articles[:MAX_ARTICLES]

    competitors = [a for a in top_regular if a["is_competitor"]]
    trends = [a for a in top_regular if not a["is_competitor"]]

    competitors.sort(key=lambda x: (x["priority"], x["published_kst"]), reverse=True)
    trends.sort(key=lambda x: (x["priority"], x["published_kst"]), reverse=True)

    # 투자유치 섹션은 최신순
    weekly_funding_articles.sort(key=lambda x: x["published_kst"], reverse=True)

    # 전부 비어 있으면 종료
    if not competitors and not trends and not weekly_funding_articles:
        send_telegram("📡 신규 기사 없음 (최근 48시간 / 중복 제외)")
        save_state(state)
        return

    msg = "📡 <b>워크랩 리서치 브리핑</b>\n(최근 48시간 / 중복 제외 / 경쟁사·기술 상위 10건)\n\n"

    # 1) 경쟁사 흐름
    if competitors:
        msg += "━━━━━━━━━━\n<b>🏢 경쟁사 흐름</b>\n━━━━━━━━━━\n\n"
        for i, a in enumerate(competitors, 1):
            company = a["company"] or "경쟁사"
            msg += format_competitor_line(i, company, a["tags"]) + "\n"
            msg += format_title_link(a["title"], a["link"]) + "\n"
            if a["snippet"]:
                msg += f"- {html.escape(a['snippet'])}\n"
            msg += "\n"

    # 2) 기술 트렌드
    if trends:
        msg += "━━━━━━━━━━\n<b>📈 기술 트렌드</b>\n━━━━━━━━━━\n\n"
        for i, a in enumerate(trends, 1):
            msg += format_trend_line(i, a["tags"]) + "\n"
            msg += format_title_link(a["title"], a["link"]) + "\n"
            if a["snippet"]:
                msg += f"- {html.escape(a['snippet'])}\n"
            msg += "\n"

    # 3) 이주의 투자유치 (항상 마지막)
    if weekly_funding_articles:
        msg += "━━━━━━━━━━\n<b>💸 이주의 투자유치</b>\n━━━━━━━━━━\n\n"
        for a in weekly_funding_articles:
            msg += f"<b>[{html.escape(a['week_label'])}]</b> · 유니콘팩토리\n"
            msg += format_title_link(a["title"], a["link"]) + "\n"
            if a["snippet"]:
                msg += f"- {html.escape(a['snippet'])}\n"
            msg += "\n"

    send_telegram(msg)

    # 전송 성공 항목들 기록
    sent_at = now_kst.isoformat()

    for a in top_regular:
        state["sent"].append({
            "url": a["link"],
            "title_norm": a["title_norm"],
            "weekly_key": "",
            "sent_at": sent_at
        })

    for a in weekly_funding_articles:
        state["sent"].append({
            "url": a["link"],
            "title_norm": a["title_norm"],
            "weekly_key": a["weekly_key"],
            "sent_at": sent_at
        })

    save_state(state)

if __name__ == "__main__":
    main()
