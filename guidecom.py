import os
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from urllib.parse import quote_plus
import re
import time
import random

"""
Guidecom 상품 검색/파싱 모듈 (app.py 수정 없이 사용)
- 요구사항: 낮은가격 3 + 인기상품 4 + 행사상품 3 = 총 10개, 중복 없이 반환
- 검색 엔드포인트 2가지 모두 지원
  1) GET  https://www.guidecom.co.kr/search/index.html?keyword=...&order=...
  2) POST https://www.guidecom.co.kr/search/list.php (keyword/order/lpp/page)
- 디버깅: 환경변수 GUIDECOM_DEBUG=1 이면 상세 로그를 콘솔(스트림릿 로그)로 출력
"""

# Product 클래스 정의
@dataclass
class Product:
    name: str
    price: str
    specifications: str
    product_link: str = ""
    site: str = ""  # "컴퓨존" 또는 "가이드컴"

class GuidecomParser:
    def __init__(self) -> None:
        self.base_url = "https://www.guidecom.co.kr/search/index.html"
        self.list_url = "https://www.guidecom.co.kr/search/list.php"
        self.ajax_url = "https://www.guidecom.co.kr/ajax/search.php"  # AJAX 엔드포인트
        self.alternative_urls = [
            "https://www.guidecom.co.kr/search/",
            "https://www.guidecom.co.kr/shop/search.html", 
            "https://www.guidecom.co.kr/shop/",
        ]
        self.debug = str(os.getenv("GUIDECOM_DEBUG", "0")).lower() in {"1", "true", "yes"}
        self.session = requests.Session()
        self.last_request_time = 0.0
        self._setup_session()

    # ----------------------- Debug helper -----------------------
    def _dbg(self, msg: str) -> None:
        if self.debug:
            print(f"[GUIDECOM][DEBUG] {msg}", flush=True)

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
        if not maker_codes:
            return True
        manufacturer = self._extract_manufacturer(product.name)
        if not manufacturer:
            return False
        man_norm = self._normalize_brand(manufacturer)
        sel_norms = [self._normalize_brand(code.replace("_", " ")) for code in maker_codes]
        for sel in sel_norms:
            if man_norm == sel or man_norm in sel or sel in man_norm:
                return True
        brand_pairs = [
            ("western digital", ["wd", "western", "digital"]),
            ("삼성전자", ["samsung", "삼성"]),
            ("asus", ["에이수스"]),
            ("gigabyte", ["기가바이트"]),
            ("zotac", ["조텍"]),
            ("nvidia", ["엔비디아"]),
            ("tp link", ["tp-link"]),
        ]
        for canonical, aliases in brand_pairs:
            if man_norm == canonical and any(a == sel for sel in sel_norms for a in aliases):
                return True
            if man_norm in aliases and any(sel == canonical for sel in sel_norms):
                return True
        return False

    # ----------------------- Public API -----------------------
    def get_search_options(self, keyword: str) -> List[Dict[str, str]]:
        """
        제조사 후보를 최대 8개까지 반환 (POST 요청 최적화)
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
                self._dbg("No results found for get_search_options")
                return []

            rows = soup.find_all("div", class_="goods-row")
            self._dbg(f"get_search_options: found {len(rows)} products")

            sample_names: List[str] = []

            # 적당한 상품에서 제조사 추출 (50개까지로 단축)
            for idx, row in enumerate(rows[:50]):
                name_el = row.select_one(".desc .goodsname1") or row.select_one(".desc h4.title a") or row.select_one("h4.title a")
                nm = self._extract_text(name_el)
                if self.debug and idx < 10:
                    sample_names.append(nm)
                maker = self._extract_manufacturer(nm)
                if maker and maker not in seen:
                    manufacturers.append(maker)
                    seen.add(maker)
                    self._dbg(f"Found manufacturer: {maker}")
                if len(manufacturers) >= 6:
                    break

            if self.debug:
                self._dbg("sample names: " + " | ".join(sample_names))
                self._dbg("manufacturers: " + ", ".join(manufacturers))

            def sort_key(x: str):
                xn = self._normalize_brand(x)
                return (0 if re.search(r"[가-힣]", x) else 1, xn)

            return [{"name": m, "code": self._normalize_brand(m).replace(" ", "_")} for m in sorted(manufacturers, key=sort_key)]
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
        try:
            order = self._resolve_order_param(sort_type)
            # 1) 다양한 방법으로 시도
            soup = self._try_alternative_methods(keyword, order)
            
            if soup:
                container = self._find_goods_list(soup)
                rows = container.find_all("div", class_="goods-row") if container else []
            else:
                rows = []
                
            self._dbg(f"search_products: order={order} rows={len(rows)}")
            out: List[Product] = []
            for row in rows:
                p = self._parse_product_item(row)
                if not p:
                    continue
                if not self._filter_by_maker(p, maker_codes):
                    continue
                out.append(p)
                if len(out) >= limit:
                    break
            self._dbg(f"search_products: returned={len(out)}")
            return out
        except Exception as e:
            self._dbg(f"search_products exception: {e}")
            return []

    def get_unique_products(self, keyword: str, maker_codes: List[str]) -> List[Product]:
        """낮은가격 3 + 인기상품 4 + 행사상품 3 = 총 10개(중복 제거)."""
        buckets: List[Tuple[str, int]] = [
            ("price_0", 3),     # 낮은가격
            ("reco_goods", 4),  # 인기상품
            ("event_goods", 3), # 행사상품
        ]
        results: List[Product] = []
        seen_names = set()

        for order, want in buckets:
            candidates = self.search_products(keyword, order, maker_codes, limit=50)
            took = 0
            for p in candidates:
                if p.name in seen_names:
                    continue
                results.append(p)
                seen_names.add(p.name)
                took += 1
                if took >= want:
                    break
        self._dbg(f"get_unique_products: total={len(results)} unique names={len(seen_names)}")
        
        # 결과가 없으면 빈 리스트 반환 (크롤링 기본 원칙)
        if not results:
            self._dbg("No products found, returning empty list")
            return []
            
        return results[:10]
