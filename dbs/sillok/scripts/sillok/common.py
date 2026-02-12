"""
실록 크롤링 공통 모듈 (sillok/common.py)
sillok_crawler.py와 sillok_update_metadata.py에서 공유하는 함수들
"""

import re
import sys
from threading import Lock

# 패키지 설치 확인
def check_and_install_packages():
    required = {
        'selenium': 'selenium',
        'webdriver_manager': 'webdriver-manager'
    }
    for pkg, pip_name in required.items():
        try:
            __import__(pkg)
        except ImportError:
            print(f"Installing {pip_name}...")
            import subprocess
            subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name])

check_and_install_packages()

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# 글로벌 Lock
print_lock = Lock()


def safe_print(*args, **kwargs):
    """스레드 안전 출력"""
    with print_lock:
        print(*args, **kwargs, flush=True)


def setup_driver():
    """Chrome 드라이버 설정 (headless)"""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x1080")
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.page_load_strategy = 'eager'
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--blink-settings=imagesEnabled=false')

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(30)
    driver.implicitly_wait(5)

    return driver


def extract_text_from_html(html: str) -> str:
    """HTML에서 태그를 제거하고 텍스트만 추출"""
    text = re.sub(r'<[^>]+>', '', html)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_footnotes(driver) -> dict:
    """
    ul.ins_footnote에서 주석 추출

    HTML 구조:
    <ul class="ins_footnote">
        <li><a href="#footnote_view1" id="footnote_1">[註 017]</a> 동기(同氣) : 송시열의 형을 말함.</li>
    </ul>

    Returns:
        {"017": {"term": "동기(同氣)", "definition": "송시열의 형을 말함."}, ...}
    """
    footnotes = {}
    try:
        footnote_list = driver.find_element(By.CSS_SELECTOR, 'ul.ins_footnote')
        items = footnote_list.find_elements(By.CSS_SELECTOR, 'li')

        for item in items:
            try:
                link = item.find_element(By.CSS_SELECTOR, 'a')
                # .text 대신 innerText 사용 (숨겨진 요소도 텍스트 추출 가능)
                link_text = link.get_attribute('innerText') or ''
                marker_match = re.search(r'\[註\s*(\d+)\]', link_text)

                if marker_match:
                    marker = marker_match.group(1)  # "017"
                    # li 전체 텍스트에서 [註 XXX] 이후 부분 추출
                    item_text = item.get_attribute('innerText') or ''
                    content = re.sub(r'\[註\s*\d+\]\s*', '', item_text)

                    # term과 definition 분리 (: 기준)
                    if ' : ' in content:
                        term, definition = content.split(' : ', 1)
                    else:
                        term, definition = "", content

                    footnotes[marker] = {
                        'term': term.strip(),
                        'definition': definition.strip()
                    }
            except NoSuchElementException:
                continue
    except NoSuchElementException:
        pass  # 주석이 없는 기사

    return footnotes


def parse_date_info(date_str: str) -> dict:
    """
    날짜 문자열 파싱

    Examples:
        "효종 1년 2월 3일 甲申 1번째기사" → 중국어 간지, N번째 형식
        "현종 즉위년 5월 4일 갑자 2/7 기사" → 한국어 간지, N/M 형식
    """
    result = {
        'reign': '',
        'year': 0,
        'month': 0,
        'day': 0,
        'ganzhi': '',
        'article_num': 1
    }

    # 왕대 추출
    reign_match = re.match(r'^(\S+)\s+', date_str)
    if reign_match:
        result['reign'] = reign_match.group(1)

    # 연월일 추출 (즉위년 = 0년)
    year_match = re.search(r'(\d+)년', date_str)
    month_match = re.search(r'(\d+)월', date_str)
    day_match = re.search(r'(\d+)일', date_str)

    if year_match:
        result['year'] = int(year_match.group(1))
    # 즉위년은 year=0으로 유지 (기본값)
    if month_match:
        result['month'] = int(month_match.group(1))
    if day_match:
        result['day'] = int(day_match.group(1))

    # 간지 추출 (중국어 + 한국어 모두 지원)
    # 중국어: 甲乙丙丁戊己庚辛壬癸 + 子丑寅卯辰巳午未申酉戌亥
    # 한국어: 갑을병정무기경신임계 + 자축인묘진사오미신유술해
    ganzhi_pattern = r'[甲乙丙丁戊己庚辛壬癸갑을병정무기경신임계][子丑寅卯辰巳午未申酉戌亥자축인묘진사오미신유술해]'
    ganzhi_match = re.search(ganzhi_pattern, date_str)
    if ganzhi_match:
        result['ganzhi'] = ganzhi_match.group(0)

    # 기사 번호 추출
    # 형식1: "N번째기사" 또는 "N번째 기사"
    # 형식2: "N/M 기사" (예: 2/7 기사)
    num_match = re.search(r'(\d+)번째', date_str)
    if num_match:
        result['article_num'] = int(num_match.group(1))
    else:
        # N/M 기사 형식
        fraction_match = re.search(r'(\d+)/\d+\s*기사', date_str)
        if fraction_match:
            result['article_num'] = int(fraction_match.group(1))

    return result


def parse_volume_info(volume_str: str) -> dict:
    """
    권수 정보 파싱
    예: "효종실록 5권" → {"sillok": "효종실록", "volume": 5}
    """
    result = {'sillok': '', 'volume': 0, 'page': ''}

    match = re.match(r'^(.+실록|.+보궐정오)\s*(\d+)권?', volume_str)
    if match:
        result['sillok'] = match.group(1).strip()
        result['volume'] = int(match.group(2))
    else:
        result['sillok'] = volume_str

    return result


def extract_categories(page_source: str) -> list:
    """
    페이지 소스에서 분류 카테고리 추출 (goBranchSearch 링크)
    """
    categories = []
    try:
        cat_matches = re.findall(r'<a[^>]*goBranchSearch[^>]*>([^<]+)</a>', page_source)
        seen = set()
        for cat in cat_matches:
            clean_cat = cat.strip()
            if clean_cat and clean_cat not in seen:
                seen.add(clean_cat)
                categories.append(clean_cat)
    except Exception:
        pass
    return categories


def extract_page_info(page_source: str) -> str:
    """
    페이지 소스에서 출전 정보 추출 (태백산사고본, 국편영인본 등)
    """
    page_info_parts = []
    try:
        # 태백산사고본 정보
        taebaek_match = re.search(r'【태백산사고본】\s*([^【\n]+)', page_source)
        if taebaek_match:
            info = re.sub(r'<[^>]+>', '', taebaek_match.group(1)).strip()
            if info:
                page_info_parts.append(f"태백산사고본 {info}")

        # 국편영인본 정보
        gukpyeon_match = re.search(r'【국편영인본】\s*([^【\n]+)', page_source)
        if gukpyeon_match:
            info = re.sub(r'<[^>]+>', '', gukpyeon_match.group(1)).strip()
            if info:
                page_info_parts.append(f"국편영인본 {info}")

        # 다른 사고본 정보 (정족산, 오대산 등)
        other_match = re.search(r'【([정족산|오대산|적상산][^】]*사고본)】\s*([^【\n]+)', page_source)
        if other_match:
            info = re.sub(r'<[^>]+>', '', other_match.group(2)).strip()
            if info:
                page_info_parts.append(f"{other_match.group(1)} {info}")
    except Exception:
        pass

    return ' / '.join(page_info_parts) if page_info_parts else ''
