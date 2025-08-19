"""
=== 통합 상품 검색기 - 가이드컴 파서 모듈 ===

이 모듈은 가이드컴(www.guidecom.co.kr) 사이트에서 PC 부품 정보를 
수집하고 파싱하는 기능을 제공합니다.

주요 기능:
- 다양한 검색 전략으로 안정적인 상품 정보 수집
- 제조사별 필터링 및 정렬 기능
- 낮은가격/인기상품/행사상품 카테고리별 검색
- 강력한 에러 처리 및 재시도 메커니즘
- 실시간 디버깅 로그 지원

검색 방식:
1. POST 방식: /search/list.php API 호출 (메인)
2. GET 방식: /search/index.html 페이지 요청 (백업)

결과 형식:
- 낮은가격 3개 + 인기상품 4개 + 행사상품 3개 = 총 10개
- 중복 제거 및 제조사 필터링 적용

환경 변수:
- GUIDECOM_DEBUG=1: 상세 디버그 로그 활성화

작성자: Claude AI
최종 수정일: 2025-01-19
"""

import os
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
from urllib.parse import quote_plus
import re
import time
import random
import traceback
from models import Product


class GuidecomParser:
    """
    가이드컴 웹사이트 파서 클래스
    
    가이드컴에서 PC 부품 정보를 크롤링하고 파싱하는 모든 기능을 담당합니다.
    다양한 검색 전략과 강력한 에러 처리를 통해 안정적인 데이터 수집을 보장합니다.
    
    주요 메서드:
    - get_search_options(): 제조사 목록 추출
    - search_products(): 단일 조건 상품 검색 
    - get_unique_products(): 다중 조건 통합 검색 (메인 API)
    
    내부 동작:
    1. 세션 초기화 및 헤더 설정
    2. 요청 간격 제어 (사이트 부하 방지)
    3. 다중 검색 전략 (POST → GET → 대체 URL)
    4. HTML 파싱 및 상품 정보 추출
    5. 제조사 필터링 및 중복 제거
    """
    
    def __init__(self) -> None:
        """
        가이드컴 파서 초기화
        
        설정되는 항목:
        1. API 엔드포인트 URL들
        2. 디버그 모드 설정
        3. HTTP 세션 초기화
        4. 요청 간격 제어 변수
        5. 브라우저 헤더 설정
        """
        # ========== API 엔드포인트 설정 ==========
        self.base_url = "https://www.guidecom.co.kr/search/index.html"     # GET 검색 페이지
        self.list_url = "https://www.guidecom.co.kr/search/list.php"       # POST API (메인)
        self.ajax_url = "https://www.guidecom.co.kr/ajax/search.php"       # AJAX 엔드포인트 (백업)
        
        # 대체 URL들 (메인 URL 실패 시 시도)
        self.alternative_urls = [
            "https://www.guidecom.co.kr/search/",           # 검색 루트
            "https://www.guidecom.co.kr/shop/search.html",  # 쇼핑 검색
            "https://www.guidecom.co.kr/shop/",             # 쇼핑 루트
        ]
        
        # ========== 디버그 모드 설정 ==========
        # 환경변수 GUIDECOM_DEBUG=1 설정 시 상세 로그 출력
        debug_env = str(os.getenv("GUIDECOM_DEBUG", "0")).lower()
        self.debug = debug_env in {"1", "true", "yes", "on"}
        
        # ========== HTTP 세션 초기화 ==========
        self.session = requests.Session()          # 쿠키 및 연결 유지용 세션
        self.last_request_time = 0.0               # 마지막 요청 시간 (간격 제어용)
        
        # ========== 브라우저 헤더 및 세션 설정 ==========
        self._setup_session()
        
        # 초기화 완료 로그
        self._dbg("가이드컴 파서 초기화 완료")
        self._dbg(f"디버그 모드: {'활성화' if self.debug else '비활성화'}")
        self._dbg(f"메인 API: {self.list_url}")
        self._dbg(f"대체 URL: {len(self.alternative_urls)}개")

    # ========== 디버그 및 유틸리티 메서드 ==========
    
    def _dbg(self, msg: str) -> None:
        """
        디버그 로그 출력 (환경변수 GUIDECOM_DEBUG=1일 때만)
        
        Args:
            msg: 출력할 디버그 메시지
        """
        if self.debug:
            print(f"[가이드컴][DEBUG] {msg}", flush=True)

    # ----------------------- Session helpers -----------------------
    def _setup_session(self) -> None:
        # 더 다양한 User-Agent로 클라우드 환경 우회
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]
        
        # 클라우드 환경에서 더 안정적인 헤더 설정
        self.session.headers.update({
            "User-Agent": random.choice(self.user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        })

    def _update_headers(self) -> None:
        self.session.headers.update({
            "User-Agent": random.choice(self.user_agents),
            "Cache-Control": random.choice(["no-cache", "max-age=0"]),
        })

    def _get_random_delay(self, a: float = 0.35, b: float = 0.9) -> float:
        return random.uniform(a, b)

    def _wait_between_requests(self, min_gap: float = 0.1) -> None:
        now = time.time()
        delta = now - self.last_request_time
        if delta < min_gap:
            time.sleep(min_gap - delta)
        self.last_request_time = time.time()

    def _fix_encoding(self, resp: requests.Response) -> None:
        try:
            # 가이드컴은 EUC-KR 사용, 항상 EUC-KR로 설정
            resp.encoding = 'euc-kr'
            self._dbg(f"Encoding set to: {resp.encoding}")
        except Exception as e:
            self._dbg(f"Encoding fix failed: {e}")
            resp.encoding = 'euc-kr'

    def _make_request(self, url: str, params: Optional[Dict[str, str]] = None, retries: int = 2) -> requests.Response:
        last_exc = None
        for attempt in range(retries):
            try:
                self._update_headers()
                self._wait_between_requests()
                
                # 재시도시 최소 대기
                if attempt > 0:
                    delay = self._get_random_delay(0.3, 0.8)
                    self._dbg(f"Retry {attempt+1}/{retries}, waiting {delay:.2f}s")
                    time.sleep(delay)
                
                # 클라우드 환경을 위한 추가 헤더
                extra_headers = {
                    "Referer": "https://www.google.com/",
                    "Origin": "https://www.guidecom.co.kr" if "guidecom.co.kr" in url else None
                }
                extra_headers = {k: v for k, v in extra_headers.items() if v}
                
                self._dbg(f"GET {url} params={params} extra_headers={extra_headers}")
                
                resp = self.session.get(
                    url, 
                    params=params, 
                    headers=extra_headers,
                    timeout=45,  # 더 긴 타임아웃
                    allow_redirects=True,
                    verify=True  # SSL 검증 활성화
                )
                
                self._fix_encoding(resp)
                self._dbg(f"GET status={resp.status_code} encoding={resp.encoding} len={len(resp.text)}")
                
                # 응답 상태 체크
                if resp.status_code == 200:
                    # 매우 관대한 조건으로 변경
                    if len(resp.text) > 50:  # 최소 50자만 있으면 통과
                        return resp
                    else:
                        self._dbg(f"Response too short: {len(resp.text)} chars")
                elif resp.status_code in [301, 302, 303, 307, 308]:
                    self._dbg(f"Redirect detected: {resp.status_code}")
                    return resp  # 리다이렉트도 허용
                else:
                    self._dbg(f"HTTP Error: {resp.status_code}")
                    self._dbg(f"Response Headers: {dict(resp.headers)}")
                    self._dbg(f"Response Text (first 300 chars): {resp.text[:300]}")
                    
            except requests.exceptions.Timeout:
                self._dbg(f"TIMEOUT on attempt {attempt+1}/{retries}")
                last_exc = RuntimeError(f"Timeout after {45}s")
            except requests.exceptions.ConnectionError as e:
                self._dbg(f"CONNECTION ERROR on attempt {attempt+1}/{retries}: {e}")
                last_exc = e
            except requests.RequestException as e:
                self._dbg(f"REQUEST ERROR on attempt {attempt+1}/{retries}: {e}")
                last_exc = e
                
        self._dbg(f"All {retries} attempts failed")
        raise last_exc if last_exc else RuntimeError("요청 실패")

    def _post_list(self, keyword: str, order: str, page: int = 1, lpp: int = 30, use_computer_parts_filter: bool = True) -> Optional[BeautifulSoup]:
        """list.php로 직접 POST하여 goods-row HTML 조각을 받는다."""
        try:
            # 먼저 메인 검색 페이지 방문으로 세션 설정
            search_page_url = f"https://www.guidecom.co.kr/search/index.html?keyword={quote_plus(keyword)}&order={order}"
            try:
                self.session.get(search_page_url, timeout=10)
            except:
                pass  # 세션 설정 실패해도 계속 진행
            
            self._update_headers()
            self._wait_between_requests()
            
            # 정확한 Referer와 헤더 설정
            headers = {
                "Referer": search_page_url,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "*/*"
            }
            data = {"keyword": keyword, "order": order, "lpp": lpp, "page": page, "y": 0}
            
            # 컴퓨터주요부품 카테고리 필터 적용
            if use_computer_parts_filter:
                # 키워드에 따라 관련성 높은 카테고리부터 시도
                keyword_lower = keyword.lower()
                
                # 빠른 카테고리 매칭 (주요 키워드만)
                priority_categories = []
                if any(k in keyword_lower for k in ["ssd", "nvme", "m.2", "solid"]):
                    priority_categories = ["8855"]  # SSD
                elif any(k in keyword_lower for k in ["rtx", "gtx", "그래픽", "gpu", "vga"]):
                    priority_categories = ["8803"]  # 그래픽카드
                elif any(k in keyword_lower for k in ["ram", "메모리", "ddr"]):
                    priority_categories = ["8802"]  # 메모리
                elif any(k in keyword_lower for k in ["cpu", "프로세서", "intel", "amd", "라이젠"]):
                    priority_categories = ["8800"]  # CPU
                elif any(k in keyword_lower for k in ["hdd", "하드", "wd", "seagate"]):
                    priority_categories = ["8804"]  # HDD
                else:
                    # 빠른 대체: 주요 3개 카테고리만 시도
                    priority_categories = ["8855", "8803", "8802"]
                
                self._dbg(f"Priority categories for '{keyword}': {priority_categories}")
                
                # 우선순위 카테고리부터 검색
                for cid in priority_categories:
                    try:
                        data_with_cid = data.copy()
                        data_with_cid["cid"] = cid
                        self._dbg(f"POST {self.list_url} with cid={cid}")
                        resp = self.session.post(self.list_url, data=data_with_cid, headers=headers, timeout=15)
                        self._fix_encoding(resp)
                        
                        if resp.status_code == 200 and len(resp.text) > 100:
                            soup = BeautifulSoup(resp.text, "lxml")
                            rows = soup.find_all("div", class_="goods-row")
                            self._dbg(f"Category {cid}: found {len(rows)} products")
                            
                            if len(rows) > 0:  # 결과가 있으면 바로 사용
                                self._dbg(f"Using category {cid} with {len(rows)} products")
                                return soup
                                
                        # 카테고리별 요청 간격 단축
                        self._wait_between_requests(0.05)
                        
                    except Exception as e:
                        self._dbg(f"Category {cid} failed: {e}")
                        continue
                
                self._dbg("No results found in priority categories, trying fallback")
            
            # 컴퓨터 부품 필터가 결과를 못 찾거나 비활성화된 경우 기본 검색
            self._dbg(f"POST {self.list_url} data={data}")
            resp = self.session.post(self.list_url, data=data, headers=headers, timeout=15)
            self._fix_encoding(resp)
            self._dbg(f"POST status={resp.status_code} encoding={resp.encoding} len={len(resp.text)}")
            if resp.status_code == 200 and len(resp.text) > 100:
                soup = BeautifulSoup(resp.text, "lxml")
                rows = soup.find_all("div", class_="goods-row")
                self._dbg(f"POST parsed goods-row={len(rows)}")
                
                # 디버그: 첫 번째 상품의 HTML 구조 확인
                if self.debug and rows:
                    self._dbg(f"=== FIRST PRODUCT HTML ===")
                    self._dbg(f"First row HTML: {str(rows[0])[:1000]}")
                    
                return soup
        except requests.RequestException as e:
            self._dbg(f"POST exception: {e}")
            return None
        return None
    
    def _try_alternative_methods(self, keyword: str, order: str) -> Optional[BeautifulSoup]:
        """다양한 방법으로 상품 데이터 가져오기 시도 - POST 중심으로 최적화"""
        methods = [
            ("POST list.php with category filter", lambda: self._post_list(keyword, order, use_computer_parts_filter=True)),
            ("POST list.php without filter", lambda: self._post_list(keyword, order, use_computer_parts_filter=False)),
        ]
        
        for method_name, method_func in methods:
            self._dbg(f"Trying method: {method_name}")
            try:
                result = method_func()
                if result and result.find_all("div", class_="goods-row"):
                    self._dbg(f"Success with method: {method_name}")
                    return result
            except Exception as e:
                self._dbg(f"Method {method_name} failed: {e}")
                
        # POST 방법이 실패한 경우만 GET 방법 시도 (fallback)
        self._dbg("POST methods failed, trying GET fallback")
        try:
            return self._get_with_params(keyword, order)
        except Exception as e:
            self._dbg(f"GET fallback failed: {e}")
            
        return None
    
    def _get_with_params(self, keyword: str, order: str) -> Optional[BeautifulSoup]:
        """GET 요청으로 직접 가져오기 (fallback용 - 실제로는 빈 템플릿만 반환)"""
        try:
            params = {"keyword": keyword, "order": order}
            resp = self._make_request(self.base_url, params=params)
            soup = BeautifulSoup(resp.text, "lxml")
            # GET 방식은 템플릿만 반환하므로 실제 상품이 없음을 로그
            self._dbg("GET method returned template page (no actual products)")
            return soup
        except Exception as e:
            self._dbg(f"GET with params failed: {e}")
            return None

    # ----------------------- Parsing helpers -----------------------
    def _find_goods_list(self, soup: BeautifulSoup):
        # 1순위: 기본 goods-list
        gl = soup.find(id="goods-list")
        if gl and gl.find_all("div", class_="goods-row"):
            self._dbg("Found products in #goods-list")
            return gl
            
        # 2순위: placeholder 내부
        placeholder = soup.find(id="goods-placeholder")
        if placeholder:
            inner = placeholder.find(id="goods-list")
            if inner and inner.find_all("div", class_="goods-row"):
                self._dbg("Found products in #goods-placeholder > #goods-list")
                return inner
        
        # 3순위: 다양한 컨테이너 ID/클래스 시도
        containers = [
            soup.find(id="product-list"),
            soup.find(id="search-results"),
            soup.find(class_="product-list"),
            soup.find(class_="search-results"),
            soup.find(class_="goods-container"),
            soup.find(class_="product-container")
        ]
        
        for container in containers:
            if container and container.find_all("div", class_="goods-row"):
                self._dbg(f"Found products in alternative container: {container.get('id') or container.get('class')}")
                return container
        
        # 4순위: 전체 soup에서 goods-row가 있는지 확인
        if soup.find_all("div", class_="goods-row"):
            self._dbg("Found goods-row in root soup")
            return soup
        
        # 5순위: 다른 가능한 상품 컨테이너들 시도
        alternative_selectors = [
            "div[class*='product']",
            "div[class*='item']", 
            "div[class*='goods']",
            ".product-item",
            ".search-item",
            ".list-item"
        ]
        
        for selector in alternative_selectors:
            items = soup.select(selector)
            if items:
                self._dbg(f"Found {len(items)} items with selector: {selector}")
                # 가짜 goods-row 구조 생성
                fake_container = soup.new_tag("div")
                for item in items[:20]:  # 최대 20개
                    item['class'] = item.get('class', []) + ['goods-row']
                    fake_container.append(item)
                return fake_container
        
        self._dbg("No product containers found anywhere")
        return soup

    def _extract_text(self, el) -> str:
        return el.get_text(" ", strip=True) if el else ""

    def _parse_price(self, text: str) -> str:
        digits = re.sub(r"[^\d]", "", text or "")
        if not digits:
            return ""
        return f"{int(digits):,}원"

    def _parse_product_item(self, row) -> Optional[Product]:
        try:
            # 디버그: 전체 row HTML 구조 출력
            if self.debug:
                self._dbg(f"=== ROW HTML DEBUG ===")
                self._dbg(f"Row classes: {row.get('class', [])}")
                self._dbg(f"Row HTML (first 500 chars): {str(row)[:500]}")
            
            # 이름: 여러 선택자 시도
            name_selectors = [
                ".desc .goodsname1",
                ".desc h4.title a", 
                "h4.title a",
                ".desc .title a",
                ".title a",
                ".desc a",
                "a"
            ]
            
            name_el = None
            product_link = ""
            for selector in name_selectors:
                name_el = row.select_one(selector)
                if name_el:
                    self._dbg(f"Found name with selector: {selector}")
                    # 링크 URL 추출 - name_el이 링크가 아닌 경우 부모 또는 형제 요소에서 링크 찾기
                    if name_el.get('href'):
                        href = name_el.get('href')
                        if href.startswith('/'):
                            product_link = f"https://www.guidecom.co.kr{href}"
                        elif href.startswith('http'):
                            product_link = href
                        else:
                            product_link = f"https://www.guidecom.co.kr/{href}"
                        self._dbg(f"Found link from name element: {product_link}")
                    else:
                        # name_el이 링크가 아닌 경우 (예: .goodsname1은 span), 부모나 형제에서 링크 찾기
                        link_el = None
                        # 1. 부모 요소가 링크인지 확인
                        parent = name_el.parent
                        if parent and parent.name == 'a' and parent.get('href'):
                            link_el = parent
                        else:
                            # 2. 같은 row 내에서 링크 찾기
                            link_selectors = [
                                ".desc h4.title a",
                                "h4.title a", 
                                ".desc .title a",
                                ".title a",
                                ".desc a",
                                "a"
                            ]
                            for link_selector in link_selectors:
                                link_el = row.select_one(link_selector)
                                if link_el and link_el.get('href'):
                                    break
                        
                        if link_el and link_el.get('href'):
                            href = link_el.get('href')
                            if href.startswith('/'):
                                product_link = f"https://www.guidecom.co.kr{href}"
                            elif href.startswith('http'):
                                product_link = href
                            else:
                                product_link = f"https://www.guidecom.co.kr/{href}"
                            self._dbg(f"Found link from separate element: {product_link}")
                    break
                    
            name = self._extract_text(name_el)
            if not name:
                self._dbg("=== NAME NOT FOUND ===")
                self._dbg(f"Available elements: {[tag.name for tag in row.find_all()]}")
                self._dbg(f"All text in row: {row.get_text(' ', strip=True)}")
                return None
                
            self._dbg(f"Product name: {name}")
            
            # 스펙 추출: 더 광범위한 선택자
            spec_selectors = [
                ".desc .feature",
                ".feature", 
                ".desc .spec",
                ".spec",
                ".desc .description",
                ".description",
                ".desc .summary",
                ".summary",
                ".desc .info",
                ".info",
                ".desc ul",
                ".desc p",
                ".goodsinfo"
            ]
            
            specs = ""
            for selector in spec_selectors:
                spec_el = row.select_one(selector)
                if spec_el:
                    specs = self._extract_text(spec_el)
                    if specs and specs != name:
                        self._dbg(f"Found specs with selector {selector}: {specs[:100]}")
                        break
                        
            if not specs:
                # 마지막 시도: .desc 내 모든 텍스트 추출
                desc_el = row.select_one(".desc")
                if desc_el:
                    # 링크 텍스트 제거하고 나머지 텍스트 가져오기
                    desc_copy = desc_el.__copy__()
                    for a_tag in desc_copy.find_all('a'):
                        a_tag.decompose()
                    specs = self._extract_text(desc_copy).strip()
                    if specs:
                        self._dbg(f"Extracted specs from .desc (no links): {specs[:100]}")
                        
            if not specs:
                self._dbg("=== SPECS NOT FOUND ===")
                desc_el = row.select_one(".desc")
                if desc_el:
                    self._dbg(f"Desc HTML: {str(desc_el)[:300]}")
                else:
                    self._dbg("No .desc element found")
                    
            # 가격 추출: 더 다양한 선택자
            price_selectors = [
                ".prices .price-large span",
                ".price-large span",
                ".price-large",
                ".prices .price span",
                ".price span", 
                ".price",
                ".cost",
                "[class*='price']"
            ]
            
            price = ""
            for selector in price_selectors:
                price_el = row.select_one(selector)
                if price_el:
                    price = self._parse_price(self._extract_text(price_el))
                    if price:
                        self._dbg(f"Found price with selector {selector}: {price}")
                        break
                        
            if not price:
                self._dbg("=== PRICE NOT FOUND ===")
                self._dbg(f"Available elements with 'price' in class: {[str(el)[:100] for el in row.find_all(class_=lambda x: x and 'price' in str(x).lower())]}")
                
            return Product(name=name, price=price or "가격 정보 없음", specifications=specs or "사양 정보 없음", product_link=product_link, site="가이드컴")
        except Exception as e:
            self._dbg(f"_parse_product_item exception: {e}")
            import traceback
            self._dbg(f"Traceback: {traceback.format_exc()}")
            return None

    # ----------------------- Manufacturer helpers -----------------------
    def _normalize_brand(self, text: str) -> str:
        t = (text or "").lower()
        t = re.sub(r"[\s._/-]+", " ", t).strip()
        aliases = {
            "wd": "western digital",
            "웨스턴 디지털": "western digital",
            "에이수스": "asus",
            "기가바이트": "gigabyte",
            "조텍": "zotac",
            "엔비디아": "nvidia",
            "삼성": "삼성전자",
            "samsung": "삼성전자",
            "g skill": "gskill",
            "tp-link": "tp link",
        }
        return aliases.get(t, t)

    def _extract_manufacturer(self, product_name: str) -> Optional[str]:
        if not product_name:
            return None
        
        self._dbg(f"Extracting manufacturer from: '{product_name}'")
        
        # 대괄호 제거 및 정리
        text = re.sub(r"\[[^\]]+\]", " ", product_name)
        text = re.sub(r"\s+", " ", text).strip()
        words = text.split()
        
        if not words:
            self._dbg("No words found after cleaning")
            return None
            
        self._dbg(f"Words after cleaning: {words}")
        
        # 건너뛸 단어들 - 더 포괄적으로 확장
        skip = {
            "신제품", "신상품", "공식인증", "병행수입", "벌크", "정품", "스페셜", "한정판",
            "8월", "7월", "6월", "9월", "10월", "11월", "12월", "1월", "2월", "3월", "4월", "5월",
            "새상품", "리퍼", "중고", "전시", "개봉", "박스", "오픈박스", "리퍼비시",
            "할인", "특가", "세일", "이벤트", "프로모션", "한정", "무료배송", "당일발송"
        }
        
        i = 0
        while i < len(words):
            word = words[i]
            self._dbg(f"Checking word '{word}' (index {i})")
            
            # 정확한 매치 또는 부분 매치 확인
            should_skip = False
            for skip_word in skip:
                if word == skip_word or skip_word in word or word in skip_word:
                    should_skip = True
                    self._dbg(f"Skipping word '{word}' (matched with '{skip_word}')")
                    break
                    
            if not should_skip:
                break
            i += 1
            
        if i >= len(words):
            self._dbg("All words were skipped, no manufacturer found")
            return None
            
        manufacturer = words[i]
        self._dbg(f"Found manufacturer candidate: '{manufacturer}'")
        
        # 2단어 브랜드 결합(Western Digital, TP LINK 등)
        if i + 1 < len(words):
            pair = f"{manufacturer} {words[i+1]}"
            normalized_pair = self._normalize_brand(pair)
            if normalized_pair in {"western digital", "tp link", "g skill", "team group"}:
                manufacturer = pair
                self._dbg(f"Combined into 2-word brand: '{manufacturer}'")
                
        self._dbg(f"Final manufacturer: '{manufacturer}'")
        return manufacturer

    def _extract_manufacturer_from_row(self, row) -> Optional[str]:
        name_el = row.select_one(".desc .goodsname1")
        if not name_el:
            name_el = row.select_one(".desc h4.title a") or row.select_one("h4.title a")
        name = self._extract_text(name_el)
        maker = self._extract_manufacturer(name)
        if self.debug:
            self._dbg(f"NAME='{name[:80]}' -> MFR='{maker}'")
        return maker

    def _filter_by_maker(self, product: Product, maker_codes: List[str]) -> bool:
        """제조사 필터링: 제품명에 선택된 제조사가 포함되면 통과"""
        if not maker_codes:
            return True
            
        product_name_lower = product.name.lower()
        
        # 핵심 로직: 제품명에 선택된 제조사 중 하나라도 포함되면 통과
        for code in maker_codes:
            code_lower = code.lower().replace("_", " ").strip()
            
            # 1. 직접 매칭: 제조사명이 제품명에 포함
            if code_lower in product_name_lower:
                return True
            
            # 2. 정규화된 브랜드명으로 매칭
            normalized_code = self._normalize_brand(code_lower)
            if normalized_code in product_name_lower:
                return True
            
            # 3. 알려진 브랜드 별칭 매칭
            brand_aliases = {
                '삼성': ['samsung', '삼성전자', 'sec'],
                'lg': ['lg전자', 'lge'],  
                'hp': ['hewlett', 'packard'],
                'asus': ['에이수스', 'asustek'],
                'msi': ['micro-star'],
                'western digital': ['wd', 'western', 'digital'],
                'seagate': ['시게이트'],
                'kingston': ['킹스톤']
            }
            
            for brand, aliases in brand_aliases.items():
                if brand == code_lower or code_lower in aliases:
                    for alias in [brand] + aliases:
                        if alias.lower() in product_name_lower:
                            return True
            
            # 4. 가이드컴/컴퓨존 특화: 병행수입업체 처리
            # 제조사명이 제품명에 없는 경우 = 유통업체일 가능성
            # 이 경우 검색 키워드와 연관성이 있으면 포함
            
            # 현재 검색 중인 키워드에서 브랜드 추출
            potential_brands = []
            if hasattr(self, '_current_search_keyword'):
                search_kw = self._current_search_keyword.lower()
                # 검색어에서 브랜드 추출
                for brand in ['삼성', 'samsung', 'lg', 'intel', 'amd', 'nvidia', 'asus', 'msi']:
                    if brand in search_kw:
                        potential_brands.append(brand)
            
            # 검색어의 브랜드가 제품명에 있으면 유통업체 제품으로 인정
            for brand in potential_brands:
                if brand in product_name_lower:
                    return True
        
        return False
    
    def _get_brand_aliases(self, brand: str) -> List[str]:
        """브랜드 별칭 목록 반환 (사용되지 않음 - 위 메서드에서 인라인 처리)"""
        return []

    def _is_generic_manufacturer(self, manufacturer: str) -> bool:
        """일반적인 용어나 의미없는 제조사명인지 유연하게 확인합니다."""
        if not manufacturer or len(manufacturer.strip()) <= 1:
            return True
        
        mfr_lower = manufacturer.lower().strip()
        
        # 1. 숫자로만 구성된 경우
        if re.match(r'^\d+$', manufacturer):
            return True
        
        # 2. 의미없는 기호나 문자
        if manufacturer in ['', ' ', '-', '_', '.', '/', '\\', '?', '!', '*']:
            return True
        
        # 3. 일반적인 형용사나 상태 표현 패턴
        generic_patterns = [
            r'신.*품',     # 신상품, 신제품 등
            r'.*가격',     # 최저가격, 할인가격 등  
            r'.*배송',     # 무료배송, 빠른배송 등
            r'.*발송',     # 당일발송, 즉시발송 등
            r'.*특가',     # 할인특가 등
            r'.*이벤트',   # 특별이벤트 등
            r'.*세일',     # 연말세일 등
            r'\d+.*월',    # 날짜 표현
            r'오전|오후|시간|분|초',  # 시간 표현
        ]
        
        for pattern in generic_patterns:
            if re.search(pattern, mfr_lower):
                return True
        
        # 4. 명확히 일반적인 명사/형용사인 경우만 제외
        # 한글로만 구성된 경우 더 정교한 분석
        if re.match(r'^[가-힣]+$', manufacturer):
            # 1글자는 의미가 모호하므로 제외
            if len(manufacturer) <= 1:
                return True
                
            # 명확히 일반적인 단어들만 제외 (구체적 패턴)
            generic_words = [
                '신제품', '신상품', '할인', '특가', '이벤트', '세일', '무료', '당일',
                '빠른', '즉시', '최저', '최고', '인기', '추천', '베스트', '핫딜',
                '오늘', '내일', '이번', '다음', '지금', '바로', '곧바로',
                '상품', '제품', '아이템', '물건', '브랜드', '회사', '업체',
                '가격', '배송', '발송', '택배', '물류', '서비스', '고객',
                '문의', '상담', '예약', '주문', '결제', '구매', '판매'
            ]
            
            # 정확히 일치하는 일반 단어들만 제외
            if manufacturer in generic_words:
                return True
                
            # 조사나 어미가 포함된 경우 (문법적으로 명사가 아님)
            if manufacturer.endswith(('에서', '으로', '부터', '까지', '에게', '에서', '께서', '에게서')):
                return True
                
            # 명사형 어미로 끝나는 경우 (동사/형용사의 명사형)
            if manufacturer.endswith(('하기', '되기', '시키기', '하는', '되는', '시키는')):
                return True
        
        return False

    def _extract_seller_info(self, row_element) -> Optional[str]:
        """HTML 요소에서 판매업체/공급업체 정보를 추출합니다."""
        if not row_element:
            return None
            
        # 다양한 선택자로 판매업체 정보 시도
        seller_selectors = [
            '.shop_name', '.seller_name', '.company_name', '.store_name',
            '.vendor', '.supplier', '[class*="shop"]', '[class*="seller"]',
            '[class*="company"]', '[class*="store"]', '.desc .company',
            '.item_shop', '.mall_name'
        ]
        
        for selector in seller_selectors:
            elements = row_element.select(selector)
            for element in elements:
                text = element.get_text(strip=True)
                if text and len(text.strip()) > 1:
                    # 간단한 정리
                    text = re.sub(r'\s+', ' ', text).strip()
                    self._dbg(f"Found seller candidate: {text}")
                    return text
        
        # 전체 텍스트에서 "파인인포", "컴퓨존" 등 알려진 업체명 찾기
        full_text = row_element.get_text()
        self._dbg(f"Full text search in: {full_text[:100]}...")
        
        known_sellers = ['파인인포', '컴퓨존', 'fineinfo', 'compuzone', '11번가', '옥션', 'G마켓']
        for seller in known_sellers:
            if seller in full_text:
                self._dbg(f"Found known seller in text: {seller}")
                return seller
                
        return None

    # ----------------------- Public API -----------------------
    def get_search_options(self, keyword: str) -> List[Dict[str, str]]:
        """
        제조사 후보를 반환 (실제 제품이 있는 제조사만)
        """
        manufacturers: List[str] = []
        seen = set()
        try:
            # 빠른 검색: 카테고리 필터링부터 시도 (더 정확한 결과)
            self._dbg("Getting manufacturers with category filter")
            soup = self._post_list(keyword, "reco_goods", use_computer_parts_filter=True)

            # 실패 시에만 전체 검색 시도
            if not soup or not soup.find_all("div", class_="goods-row"):
                self._dbg("Fallback to unfiltered POST")
                soup = self._post_list(keyword, "reco_goods", use_computer_parts_filter=False)

            if not soup or not soup.find_all("div", class_="goods-row"):
                self._dbg("No results found for get_search_options - returning empty list")
                return []  # 실제 제품이 없으면 빈 목록 반환

            rows = soup.find_all("div", class_="goods-row")
            self._dbg(f"get_search_options: found {len(rows)} products")

            sample_names: List[str] = []
            manufacturer_counts = {}  # 제조사별 제품 개수 카운트

            # 적당한 상품에서 제조사 및 판매업체 추출 (50개까지로 단축)
            for idx, row in enumerate(rows[:50]):
                name_el = row.select_one(".desc .goodsname1") or row.select_one(".desc h4.title a") or row.select_one("h4.title a")
                nm = self._extract_text(name_el)
                if self.debug and idx < 10:
                    sample_names.append(nm)
                
                # 1. 제품명에서 제조사 추출 (기존 로직)
                maker = self._extract_manufacturer(nm)
                if maker and not self._is_generic_manufacturer(maker):
                    manufacturer_counts[maker] = manufacturer_counts.get(maker, 0) + 1
                    if maker not in seen:
                        manufacturers.append(maker)
                        seen.add(maker)
                        self._dbg(f"Found manufacturer: {maker}")
                
                # 2. 판매업체/공급업체 정보 추출 (새로운 로직)
                seller_info = self._extract_seller_info(row)
                self._dbg(f"Seller extraction result: {seller_info}")
                if seller_info and not self._is_generic_manufacturer(seller_info):
                    manufacturer_counts[seller_info] = manufacturer_counts.get(seller_info, 0) + 1
                    if seller_info not in seen:
                        manufacturers.append(seller_info)
                        seen.add(seller_info)
                        self._dbg(f"Found seller/supplier: {seller_info}")

            # 1개 이상의 제품을 가진 제조사 필터링 (모든 제조사 포함)
            filtered_manufacturers = []
            for manufacturer in manufacturers:
                if manufacturer_counts.get(manufacturer, 0) >= 1:  # 1개 이상으로 변경
                    filtered_manufacturers.append(manufacturer)


            if self.debug:
                self._dbg("sample names: " + " | ".join(sample_names))
                self._dbg("filtered manufacturers: " + ", ".join(filtered_manufacturers))

            def sort_key(x: str):
                xn = self._normalize_brand(x)
                return (0 if re.search(r"[가-힣]", x) else 1, xn)

            return [{"name": m, "code": self._normalize_brand(m).replace(" ", "_")} for m in sorted(filtered_manufacturers[:12], key=sort_key)]
        except Exception as e:
            self._dbg(f"get_search_options exception: {e}")
            return []

    def _resolve_order_param(self, sort_type: str) -> str:
        mapping = {
            "price_0": "price_0",
            "낮은가격": "price_0",
            "priceasc": "price_0",
            "reco_goods": "reco_goods",
            "인기상품": "reco_goods",
            "opiniondesc": "reco_goods",
            "event_goods": "event_goods",
            "행사상품": "event_goods",
            "savedesc": "event_goods",
        }
        k = (sort_type or "").lower()
        return mapping.get(k, "reco_goods")

    def search_products(self, keyword: str, sort_type: str, maker_codes: List[str], limit: int = 5) -> List[Product]:
        """단일 정렬 기준으로 제품 최대 `limit`개 반환 (list.php 우선)."""
        # 검색 키워드 저장 (필터링에서 사용)
        self._current_search_keyword = keyword
        try:
            self._dbg(f"가이드컴 제품 검색 시작: '{keyword}', 제조사: {maker_codes}, 한도: {limit}")
            
            order = self._resolve_order_param(sort_type)
            # 1) 다양한 방법으로 시도
            soup = self._try_alternative_methods(keyword, order)
            
            if soup:
                container = self._find_goods_list(soup)
                rows = container.find_all("div", class_="goods-row") if container else []
            else:
                rows = []
                
            self._dbg(f"search_products: order={order} rows={len(rows)}")
            
            if not rows:
                self._dbg("가이드컴에서 상품을 찾을 수 없습니다.")
                return []
            
            out: List[Product] = []
            for idx, row in enumerate(rows):
                p = self._parse_product_item(row)
                if not p:
                    self._dbg(f"상품 {idx+1} 파싱 실패")
                    continue
                if not self._filter_by_maker(p, maker_codes):
                    self._dbg(f"상품 '{p.name[:30]}...' 제조사 필터에서 제외됨")
                    continue
                out.append(p)
                self._dbg(f"상품 추가: '{p.name[:30]}...' - {p.price}")
                if len(out) >= limit:
                    break
            
            self._dbg(f"가이드컴 최종 결과: {len(out)}개 상품")
            return out
        except Exception as e:
            self._dbg(f"search_products exception: {e}")
            import traceback
            self._dbg(f"Traceback: {traceback.format_exc()}")
            return []

    def get_unique_products(self, keyword: str, maker_codes: List[str]) -> List[Product]:
        """
        🎯 가이드컴 메인 검색 API - 다중 카테고리 통합 검색
        
        3가지 카테고리에서 상품을 검색하여 총 10개의 중복 없는 결과를 반환합니다.
        
        검색 전략:
        - 낮은가격: 3개 (가격 경쟁력 있는 상품)
        - 인기상품: 4개 (판매량/평점 기반 인기 상품)  
        - 행사상품: 3개 (할인/프로모션 상품)
        
        Args:
            keyword: 검색할 키워드 (예: "SSD", "RTX 4090")
            maker_codes: 제조사 필터 코드 리스트 (빈 리스트면 전체)
            
        Returns:
            List[Product]: 최대 10개의 중복 없는 상품 리스트
            
        동작 방식:
        1. 각 카테고리별로 순차 검색 수행
        2. 중복 상품명 제거 (seen_names로 관리)
        3. 카테고리별 목표 개수 달성 시 다음 카테고리로 이동
        4. 전체 결과를 10개로 제한하여 반환
        
        실패 처리:
        - 어떤 카테고리에서 검색 실패해도 다른 카테고리 계속 진행
        - 모든 카테고리에서 실패하면 빈 리스트 반환
        """
        try:
            self._dbg(f"=== 가이드컴 통합 검색 시작 ===")
            self._dbg(f"검색어: '{keyword}', 제조사 필터: {len(maker_codes)}개")
            
            # ========== 카테고리별 검색 전략 정의 ==========
            search_buckets = [
                ("price_0", 3, "낮은가격"),      # 가격순 정렬, 3개
                ("reco_goods", 4, "인기상품"),   # 인기순 정렬, 4개  
                ("event_goods", 3, "행사상품"),  # 할인순 정렬, 3개
            ]
            
            all_results: List[Product] = []
            seen_names = set()  # 중복 제거용 상품명 집합
            total_attempted = 0
            
            # ========== 카테고리별 순차 검색 ==========
            for order_type, target_count, category_name in search_buckets:
                try:
                    self._dbg(f"\n--- {category_name} 카테고리 검색 (목표: {target_count}개) ---")
                    
                    # 해당 카테고리에서 후보 상품들을 충분히 가져오기 (목표의 10배)
                    candidates = self.search_products(
                        keyword=keyword, 
                        sort_type=order_type, 
                        maker_codes=maker_codes, 
                        limit=target_count * 10  # 넉넉하게 가져와서 선별
                    )
                    
                    category_added = 0
                    
                    # 후보 상품들 중에서 중복되지 않는 것들만 선별
                    for product in candidates:
                        if not product or not product.name:
                            continue
                            
                        # 중복 검사 (상품명 기준)
                        if product.name in seen_names:
                            continue
                        
                        # 새로운 상품 추가
                        all_results.append(product)
                        seen_names.add(product.name)
                        category_added += 1
                        total_attempted += 1
                        
                        self._dbg(f"  추가: {product.name[:40]}... - {product.price}")
                        
                        # 카테고리별 목표 달성 시 중단
                        if category_added >= target_count:
                            break
                    
                    self._dbg(f"  {category_name} 완료: {category_added}개 추가 (총 {len(all_results)}개)")
                    
                except Exception as e:
                    self._dbg(f"  {category_name} 카테고리 검색 실패: {e}")
                    continue  # 이 카테고리는 실패해도 다음 카테고리 계속 진행
            
            # ========== 최종 결과 정리 ==========
            final_count = min(len(all_results), 10)  # 최대 10개로 제한
            final_results = all_results[:final_count]
            
            self._dbg(f"\n=== 가이드컴 통합 검색 완료 ===")
            self._dbg(f"총 검색 시도: {total_attempted}개")
            self._dbg(f"중복 제거 후: {len(all_results)}개")
            self._dbg(f"최종 반환: {final_count}개")
            
            # 결과가 없으면 빈 리스트 반환
            if not final_results:
                self._dbg("[WARNING] 모든 카테고리에서 상품을 찾지 못함")
                return []
            
            # 결과 요약 로그
            for i, product in enumerate(final_results, 1):
                self._dbg(f"  {i}. {product.name[:30]}... - {product.price} ({product.site})")
            
            return final_results
            
        except Exception as e:
            self._dbg(f"통합 검색 전체 실패: {e}")
            import traceback
            self._dbg(f"상세 오류: {traceback.format_exc()}")
            return []
