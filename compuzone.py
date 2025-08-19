"""
=== 통합 상품 검색기 - 컴퓨존 파서 모듈 ===

컴퓨존(www.compuzone.co.kr)에서 PC 부품 정보를 검색하고 파싱하는 모듈입니다.

주요 기능:
1. 키워드 기반 제조사 검색: 검색어에 따른 관련 제조사 추출
2. 제품 검색: 제조사 필터링과 함께 상품 정보 수집
3. 다중 검색 전략: API 실패 시 백업 전략 자동 적용
4. 동적 브랜드 매칭: 유연한 제조사 필터링 시스템
5. 옵션 상품 처리: 용량별/팩별 옵션 상품 개별 파싱

기술적 특징:
- EUC-KR 인코딩 지원으로 한글 깨짐 방지
- 실제 브라우저 헤더 모방으로 차단 회피
- 3단계 검색 전략으로 안정성 확보
- 중복 제거 및 스마트 필터링
- 상품 옵션 및 가격 범위 처리

사용 예시:
    >>> parser = CompuzoneParser()
    >>> manufacturers = parser.get_search_options("SSD 1TB")
    >>> products = parser.search_products("SSD 1TB", "sale_order", ["2"], 10)

작성자: Claude AI
최종 수정일: 2025-01-19
"""

# -*- coding: utf-8 -*-
import requests
import re
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
import urllib.parse
from models import Product

class CompuzoneParser:
    """
    컴퓨존 웹사이트 파서 클래스
    
    컴퓨존에서 PC 부품 정보를 검색하고 파싱하는 전용 클래스입니다.
    실제 사이트 구조를 분석하여 최적화된 다중 검색 전략을 사용합니다.
    
    Attributes:
        session (requests.Session): HTTP 세션 관리 객체
        base_url (str): 컴퓨존 기본 검색 페이지 URL
        search_api_url (str): 검색 결과 API 엔드포인트 URL
    
    주요 기능:
        - 브라우저 환경 모방으로 안정적인 웹 스크래핑
        - EUC-KR 인코딩 처리로 한글 데이터 정확성 보장
        - 3단계 검색 전략으로 높은 성공률 확보
        - 제조사 필터링 및 브랜드 매칭 시스템
    """
    
    def __init__(self):
        """
        CompuzoneParser 인스턴스를 초기화합니다.
        
        실제 브라우저와 동일한 HTTP 헤더를 설정하여 
        웹사이트 차단을 방지하고 안정적인 데이터 수집을 보장합니다.
        """
        # HTTP 세션 생성 및 브라우저 헤더 설정
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3',  # 한국어 우선
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        
        # 컴퓨존 URL 설정
        self.base_url = "https://www.compuzone.co.kr/search/search.htm"          # 메인 검색 페이지
        self.search_api_url = "https://www.compuzone.co.kr/search/search_list.php"  # 검색 결과 API

    def _format_price(self, price_text: str) -> str:
        """
        가격 텍스트를 표준 형식으로 변환합니다.
        
        다양한 형태의 가격 정보를 "123,456원" 형식으로 통일하고,
        특수 상태(품절, 가격문의)를 표준화합니다.
        
        Args:
            price_text (str): 원본 가격 텍스트
            
        Returns:
            str: 표준화된 가격 문자열
                - "123,456원": 정상 가격
                - "품절": 재고 없음
                - "가격 문의": 별도 문의 필요
                - "가격 정보 없음": 파싱 실패
        """
        if not price_text:
            return "가격 정보 없음"
        
        # 숫자만 추출
        price_clean = re.sub(r'[^\d]', '', price_text)
        if price_clean:
            try:
                return f"{int(price_clean):,}원"
            except ValueError:
                pass
        
        # 특수 문구 처리
        if any(word in price_text for word in ['문의', '전화', '연락']):
            return "가격 문의"
        
        return price_text
    
    def _check_brand_match(self, product_name: str, maker_codes: List[str]) -> bool:
        """
        제품명 기반 간단한 브랜드 매칭 시스템
        
        복잡한 ID 매핑 대신 제품명에서 직접 브랜드를 찾는 방식:
        1. 제품명에 선택된 제조사명이 포함되어 있으면 통과
        2. 브랜드 별칭을 고려한 유연한 매칭
        3. 대소문자, 공백 무시
        
        Args:
            product_name (str): 제품명 (예: "[삼성전자] 990 EVO 1TB")
            maker_codes (List[str]): 선택된 제조사 코드 목록
            
        Returns:
            bool: 매칭 성공 시 True, 실패 시 False
        """
        if not maker_codes:
            return True
            
        product_name_lower = product_name.lower()
        
        # 핵심 로직: 제품명에 선택된 제조사 중 하나라도 포함되면 통과
        for code in maker_codes:
            code_lower = code.lower().replace("_", " ").strip()
            
            # 1. 직접 매칭: 제조사명이 제품명에 포함
            if code_lower in product_name_lower:
                return True
            
            # 2. 브랜드 별칭 매칭: 다양한 표기법 지원
            if self._check_brand_aliases(product_name_lower, code_lower):
                return True
        
        return False
    
    def _check_brand_aliases(self, product_name_lower: str, code_lower: str) -> bool:
        """브랜드 별칭을 확인하여 매칭"""
        # 간단한 별칭 매핑 (가장 중요한 것만)
        alias_map = {
            'amd': ['amd', '라이젠', 'ryzen'],
            'intel': ['intel', '인텔', '코어', 'core'],
            'samsung': ['삼성', 'samsung', '삼성전자'],
            'nvidia': ['nvidia', '지포스', 'geforce', 'rtx', 'gtx'],
            'asus': ['asus', '에이수스'],
            'msi': ['msi'],
            'gigabyte': ['gigabyte', '기가바이트'],
            'western digital': ['wd', 'western digital', '웨스턴디지털'],
            'seagate': ['seagate', '시게이트'],
        }
        
        for brand_key, aliases in alias_map.items():
            if code_lower in aliases:
                # 제품명에 같은 그룹의 다른 별칭이 있는지 확인
                for alias in aliases:
                    if alias in product_name_lower:
                        return True
        
        return False
        
    def _get_brand_mapping(self) -> dict:
        """
        컴퓨존에서 사용하는 제조사 ID와 브랜드명 매핑을 반환합니다.
        
        실제 사이트 분석을 통해 확인된 정확한 매핑만 포함하여
        잘못된 브랜드 매칭을 방지합니다.
        
        Returns:
            dict: {제조사_ID: 브랜드명} 형태의 매핑 딕셔너리
                 예: {'2': '삼성전자', '24': 'Western Digital'}
        """
        return {
            # 주요 CPU 브랜드
            '8': 'AMD',                            # AMD 프로세서 (라이젠 등)
            '1': 'INTEL',                          # 인텔 프로세서
            
            # 주요 저장장치 브랜드
            '2': '삼성전자', '6202': '삼성전자',
            '24': 'Western Digital', '25': 'SEAGATE',
            '6348': 'Crucial', '18': 'Kingston', '242': 'Transcend',
            '3400': 'ADATA', '20': '마이크론', '566': '하이디스크',
            '6549': '티맥스솔루션', '14948': 'SK hynix',
            
            # 주요 그래픽카드 브랜드  
            '14': 'GIGABYTE', '9': 'ASUS', '475': 'MSI',
            '1111': 'PNY', '8842': 'PALIT', '2416': 'ZOTAC',
            '6238': 'INNO3D', '32': 'GAINWARD', '3169': 'MANLI',
            
            # 기타 PC부품 브랜드
            '99': 'HP', '763': 'Corsair', '1046': 'Patriot',
            '1419': 'G.SKILL', '4629': '레노버'
        }
        
    def _brands_match(self, brand1: str, brand2: str) -> bool:
        """두 브랜드명이 같은지 비교 (대소문자 및 공백 무시)"""
        return brand1.upper().strip() == brand2.upper().strip()
        
    def _flexible_brand_match(self, bracket_brand: str, code: str) -> bool:
        """유연한 브랜드 매칭 (부분 매칭 등)"""
        bracket_upper = bracket_brand.upper().strip()
        code_upper = code.upper().strip()
        
        # 어느 한쪽이 다른 쪽에 포함되는지 확인
        if len(bracket_upper) >= 3 and len(code_upper) >= 3:
            return (bracket_upper in code_upper or code_upper in bracket_upper)
            
        return False

    def _get_manufacturer_from_search_api(self, keyword: str) -> List[Dict[str, str]]:
        """
        컴퓨존 검색 API에서 제조사 정보를 직접 추출합니다.
        
        컴퓨존의 search_list.php API를 호출하여 검색어에 관련된
        제조사 체크박스 정보를 파싱합니다. 가장 빠르고 정확한 방법입니다.
        
        Args:
            keyword (str): 검색 키워드 (예: "SSD", "그래픽카드")
            
        Returns:
            List[Dict[str, str]]: 제조사 정보 리스트
                각 딕셔너리는 {'name': 브랜드명, 'code': ID} 형태
                예: [{'name': '삼성전자', 'code': '2'}]
                
        Process:
            1. 메인 검색 페이지 방문으로 세션 설정
            2. API 파라미터로 제조사 정보 요청
            3. HTML에서 체크박스 요소 파싱
            4. 브랜드명과 ID 추출 및 정리
        """
        try:
            # 메인 페이지 먼저 방문 (쿠키 설정용)
            encoded_keyword = urllib.parse.quote(keyword, encoding='utf-8')
            search_url = f"{self.base_url}?SearchProductKey={encoded_keyword}"
            self.session.get(search_url, timeout=10)
            
            # API 호출로 제조사 체크박스 포함된 HTML 가져오기
            params = {
                "actype": "list",
                "SearchType": "small",
                "SearchText": keyword,
                "PreOrder": "sale_order",
                "PageCount": "20",
                "StartNum": "0",
                "PageNum": "1",
                "ListType": "0",
                "BigDivNo": "4",  # 컴퓨터부품 카테고리
                "MediumDivNo": "",
                "DivNo": "",
                "MinPrice": "0",
                "MaxPrice": "0",
                "ChkMakerNo": "",
                "sub_actype": "maker"  # 제조사 정보 요청
            }
            
            headers = {
                "Accept": "*/*",
                "Referer": search_url,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
            }
            
            resp = self.session.get(self.search_api_url, params=params, headers=headers, timeout=10)
            resp.encoding = 'euc-kr'
            resp.raise_for_status()
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # 제조사 체크박스 추출
            checkbox_selectors = [
                'input[name_vals*="|"][vals]',
                'input[class*="chkMedium"][vals]',
                'input[onclick*="chk_maker"][vals]',
                'input[id^="chk"][vals]'
            ]
            
            manufacturers = []
            
            for selector in checkbox_selectors:
                manufacturer_checkboxes = soup.select(selector)
                if manufacturer_checkboxes:
                    print(f"API에서 제조사 체크박스 {len(manufacturer_checkboxes)}개 발견")
                    
                    for checkbox in manufacturer_checkboxes:
                        vals = checkbox.get('vals')  # 제조사 ID (숫자)
                        name_vals = checkbox.get('name_vals', '')
                        
                        if vals and vals.isdigit():  # 숫자 ID만 사용
                            brand_name = ''
                            
                            # name_vals에서 브랜드명 추출 (형식: "브랜드|ID")
                            if name_vals and '|' in name_vals:
                                brand_name = name_vals.split('|')[0]
                            
                            # label에서도 시도
                            if not brand_name:
                                checkbox_id = checkbox.get('id', '')
                                if checkbox_id:
                                    label = soup.find('label', {'for': checkbox_id})
                                    if label:
                                        label_text = label.get_text(strip=True)
                                        # 괄호와 숫자 제거
                                        brand_name = re.sub(r'\s*\(\d+\)\s*$', '', label_text)
                            
                            if brand_name:
                                manufacturers.append({'name': brand_name, 'code': vals})
                                print(f"  - {brand_name} (ID: {vals})")
                    
                    if manufacturers:
                        break
            
            return manufacturers[:20]
            
        except Exception as e:
            print(f"API에서 제조사 추출 실패: {e}")
            return []
    
    def _get_known_manufacturer_ids(self, keyword: str) -> List[Dict[str, str]]:
        """알려진 제조사 ID 매핑을 반환합니다."""
        # 제공받은 분석 자료에서 확인된 제조사 ID들
        known_manufacturers = {
            '삼성전자': '2',
            'HP': '99',
            '레노버': '4629',
            # 추가 제조사들 (추정)
            'LG전자': '3',
            'ASUS': '100',
            'MSI': '101',
            'GIGABYTE': '102',
            'Western Digital': '200',
            'Seagate': '201',
            'Kingston': '300',
            'Crucial': '301',
            'INTEL': '400',
            'AMD': '401',
        }
        
        manufacturers = []
        
        # 키워드에 따라 관련 제조사들만 반환
        keyword_lower = keyword.lower()
        
        if any(k in keyword_lower for k in ['ssd', 'nvme', 'storage', '저장']):
            # 저장장치 관련 제조사
            relevant_brands = ['삼성전자', 'Western Digital', 'Seagate', 'Kingston', 'Crucial']
        elif any(k in keyword_lower for k in ['cpu', 'processor', '프로세서']):
            # CPU 관련 제조사
            relevant_brands = ['INTEL', 'AMD']
        elif any(k in keyword_lower for k in ['gpu', 'graphic', '그래픽']):
            # GPU 관련 제조사
            relevant_brands = ['ASUS', 'MSI', 'GIGABYTE']
        elif any(k in keyword_lower for k in ['notebook', 'laptop', '노트북']):
            # 노트북 관련 제조사
            relevant_brands = ['삼성전자', 'LG전자', 'HP', '레노버', 'ASUS']
        else:
            # 일반적인 제조사들
            relevant_brands = list(known_manufacturers.keys())[:10]
        
        for brand in relevant_brands:
            if brand in known_manufacturers:
                manufacturers.append({'name': brand, 'code': known_manufacturers[brand]})
        
        return manufacturers

    def _get_manufacturers_from_actual_products(self, keyword: str) -> List[Dict[str, str]]:
        """실제 검색된 제품들에서 제조사를 추출합니다."""
        try:
            # 제조사 필터링 없이 전체 제품 검색
            encoded_keyword = urllib.parse.quote(keyword, encoding='utf-8')
            search_url = f"{self.base_url}?SearchProductKey={encoded_keyword}"
            
            # 검색 페이지 접근
            resp = self.session.get(search_url, timeout=10)
            resp.encoding = 'utf-8'
            resp.raise_for_status()
            
            # API 호출로 실제 제품 목록 가져오기 (컴퓨터부품 카테고리로 제한)
            params = {
                "actype": "list",
                "SearchType": "small",
                "SearchText": keyword,
                "PreOrder": "sale_order",
                "PageCount": "100",  # 더 많은 제품을 가져와서 제조사 추출
                "StartNum": "0",
                "PageNum": "1",
                "ListType": "0",
                "BigDivNo": "4",  # 컴퓨터부품 카테고리
                "MediumDivNo": "",
                "DivNo": "",
                "MinPrice": "0",
                "MaxPrice": "0",
                "ChkMakerNo": ""
            }
            
            headers = {
                "Accept": "*/*",
                "Referer": search_url,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
            }
            
            resp = self.session.get(self.search_api_url, params=params, headers=headers, timeout=10)
            resp.encoding = 'euc-kr'
            resp.raise_for_status()
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # 제품 아이템에서 제조사 추출
            product_items = soup.select("li.li-obj")
            manufacturers_found = {}  # {브랜드명: ID} 형태로 저장
            
            print(f"실제 검색된 제품 수: {len(product_items)}개")
            
            for item in product_items:
                product_name_tag = item.select_one(".prd_info_name.prdTxt, .prd_info_name")
                if product_name_tag:
                    product_name = product_name_tag.get_text(strip=True)
                    
                    # [브랜드] 형식에서 브랜드 추출
                    bracket_brand_match = re.search(r'\[([^\]]+)\]', product_name)
                    if bracket_brand_match:
                        brand_name = bracket_brand_match.group(1)
                        
                        # 해당 브랜드의 제조사 ID 찾기 (API 호출을 통해)
                        if brand_name not in manufacturers_found:
                            brand_id = self._find_manufacturer_id_for_brand(brand_name, keyword)
                            if brand_id:
                                manufacturers_found[brand_name] = brand_id
                                print(f"  - {brand_name} (ID: {brand_id})")
            
            # 결과를 리스트로 변환
            result = []
            for brand_name, brand_id in manufacturers_found.items():
                result.append({'name': brand_name, 'code': brand_id})
            
            print(f"실제 제품이 있는 제조사: {len(result)}개")
            return result[:12]  # 최대 12개까지
            
        except Exception as e:
            print(f"실제 제품에서 제조사 추출 실패: {e}")
            return []

    def _find_manufacturer_id_for_brand(self, brand_name: str, keyword: str) -> Optional[str]:
        """특정 브랜드의 제조사 ID를 찾습니다."""
        try:
            # API에서 제조사 체크박스 추출하여 해당 브랜드 ID 찾기
            manufacturers_from_api = self._get_manufacturer_from_search_api(keyword)
            
            for mfr in manufacturers_from_api:
                if mfr['name'].lower() == brand_name.lower():
                    return mfr['code']
            
            # 알려진 제조사 매핑에서도 찾기
            known_mapping = {
                '삼성전자': '2', 'HP': '99', '레노버': '4629',
                'Western Digital': '24', 'SEAGATE': '25', 'ADATA': '3400',
                '동화': '439', 'SEBAP': '10219', 'HPE': '15947'
            }
            
            return known_mapping.get(brand_name)
            
        except Exception as e:
            print(f"브랜드 {brand_name}의 ID 찾기 실패: {e}")
            return None

    def _extract_brands_from_search_results(self, keyword: str) -> List[Dict[str, str]]:
        """실제 검색 결과에서 브랜드를 추출합니다 (간단한 방법)."""
        try:
            # 기본 제품 검색 (제조사 필터링 없이)
            products = self.search_products(keyword, "sale_order", [], limit=50)
            
            # 제품명에서 브랜드 추출
            brands_found = {}  # {브랜드명: 개수} 형태로 저장
            
            print(f"검색된 제품 수: {len(products)}개")
            
            for product in products:
                # [브랜드] 형식 추출
                bracket_match = re.search(r'\[([^\]]+)\]', product.name)
                if bracket_match:
                    brand_name = bracket_match.group(1).strip()
                    if len(brand_name) > 1:  # 너무 짧은 것 제외
                        brands_found[brand_name] = brands_found.get(brand_name, 0) + 1
                        if len(brands_found) <= 5:  # 처음 5개만 디버그 출력
                            print(f"  브랜드 발견: [{brand_name}] from {product.name[:40]}...")
            
            # 알려진 제조사 ID 매핑 (더 포괄적으로)
            known_ids = {
                'SEBAP': '10219', 'Western Digital': '24', '동화': '439', 
                'SEAGATE': '25', 'HPE': '15947', '삼성전자': '2', 
                'HP': '99', '레노버': '4629', 'ASUS': '9', 'MSI': '475',
                'GIGABYTE': '14', 'ADATA': '3400', 'Crucial': '6348',
                'Kingston': '18', 'Corsair': '763', 'G.SKILL': '1419',
                '지스킬': '1419', 'TeamGroup': '1419', 'TEAMGROUP': '1419',
                'CORSAIR': '763', 'Patriot': '1046', 'KINGMAX': '18',
                # HTML 체크박스에서 확인된 그래픽카드 제조사들
                'MANLI': '3169', 'PNY': '1111', 'PALIT': '8842',
                'ZOTAC': '2416', 'Thermal grizzly': '8231', 'INNO3D': '6238',
                'GAINWARD': '32'
            }
            
            # 제품 개수 기준으로 정렬 (실제로 많이 나오는 브랜드 우선)
            sorted_brands = sorted(brands_found.items(), key=lambda x: x[1], reverse=True)
            
            # 결과 생성
            result = []
            for brand_name, count in sorted_brands:
                # 알려진 ID가 있으면 사용, 없으면 브랜드명을 ID로 사용
                brand_id = known_ids.get(brand_name, brand_name)
                result.append({'name': brand_name, 'code': brand_id})
            
            print(f"실제 제품에서 추출한 브랜드: {len(result)}개")
            for brand in result[:10]:  # 처음 10개만 표시
                count = brands_found[brand['name']]
                print(f"  - {brand['name']} (ID: {brand['code']}) - {count}개 제품")
            
            return result[:12]  # 최대 12개까지
            
        except Exception as e:
            print(f"브랜드 추출 실패: {e}")
            return []

    def get_search_options(self, keyword: str) -> List[Dict[str, str]]:
        """컴퓨존에서 검색 결과를 통해 브랜드를 추출합니다."""
        try:
            # 1단계: API에서 직접 제조사 정보 가져오기 (가장 빠름)
            manufacturers = self._get_manufacturer_from_search_api(keyword)
            if manufacturers:
                print(f"API를 통해 제조사 {len(manufacturers)}개 즉시 확인")
                return manufacturers

            # 2단계: API 실패 시, 실제 제품 목록에서 브랜드 추출 (느리지만 정확)
            print("API 제조사 검색 실패, 실제 제품에서 브랜드 추출 시도")
            manufacturers_from_products = self._extract_brands_from_search_results(keyword)
            if manufacturers_from_products:
                print(f"실제 제품에서 제조사 {len(manufacturers_from_products)}개 추출 성공")
                return manufacturers_from_products
            
            # 3단계: 그래도 없으면, 알려진 제조사 ID 목록 반환 (최후의 수단)
            print("최종 수단: 알려진 제조사 ID 목록 반환")
            return self._get_known_manufacturer_ids(keyword)
            
            # 기존 코드 (이제 사용되지 않음)
            # URL 인코딩된 검색어로 요청
            encoded_keyword = urllib.parse.quote(keyword, encoding='utf-8')
            search_url = f"{self.base_url}?SearchProductKey={encoded_keyword}"
            
            # 먼저 검색 페이지에 접근
            resp = self.session.get(search_url, timeout=10)
            resp.encoding = 'euc-kr'  # 컴퓨존은 EUC-KR 인코딩 사용
            resp.raise_for_status()
            
            # 검색 결과 목록 가져오기
            params = {
                "actype": "list",
                "SearchType": "small", 
                "SearchText": keyword,
                "PreOrder": "sale_order",
                "PageCount": "50",
                "StartNum": "0",
                "PageNum": "1",
                "ListType": "0",
                "BigDivNo": "",
                "MediumDivNo": "",
                "DivNo": "",
                "MinPrice": "0",
                "MaxPrice": "0"
            }
            
            headers = {
                "Accept": "*/*",
                "Referer": search_url,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
            }
            
            resp = self.session.get(self.search_api_url, params=params, headers=headers, timeout=10)
            resp.encoding = 'euc-kr'  # 컴퓨존은 EUC-KR 인코딩 사용
            resp.raise_for_status()
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # 제품명에서 브랜드 추출
            product_items = soup.select("li.li-obj")
            brands = set()
            
            # 확장된 PC 부품 브랜드 리스트 (더 포괄적)
            common_brands = [
                # 그래픽카드 브랜드
                'ASUS', 'MSI', 'GIGABYTE', 'EVGA', 'ZOTAC', 'PALIT', 'GALAX', 'INNO3D', 'SAPPHIRE',
                'XFX', 'POWERCOLOR', 'HIS', 'GAINWARD', 'PNY', 'LEADTEK', 'MANLI', 'AFOX',
                # 메모리/저장장치 브랜드
                'SAMSUNG', '삼성전자', 'SK하이닉스', 'CRUCIAL', 'KINGSTON', 'WD', 'Seagate', 'TOSHIBA',
                'G.SKILL', 'TEAMGROUP', 'ADATA', 'PATRIOT', 'HYPERX', 'GEIL', 'MUSHKIN', 'CORSAIR',
                # 파워/케이스 브랜드  
                '마이크로닉스', 'SEASONIC', 'COOLER MASTER', 'THERMALTAKE', 'ANTEC', 'FSP', 'SILVERSTONE',
                # CPU/칩셋 브랜드
                'INTEL', 'AMD', 'NVIDIA', 
                # 주변기기/모니터 브랜드
                'LG전자', 'HP', 'DELL', 'LENOVO', 'ACER', 'BENQ', 'VIEWSONIC', 'AOC',
                # 기타 PC 브랜드
                'RAZER', 'LOGITECH', 'STEELSERIES', 'ROCCAT', 'REDRAGON', 'ABKO', '레오폴드'
            ]
            
            for item in product_items:
                product_name_tag = item.select_one(".prd_info_name.prdTxt")
                if product_name_tag:
                    product_name = product_name_tag.get_text(strip=True)
                    
                    # 컴퓨존의 [브랜드] 형식 추출
                    bracket_brand_match = re.search(r'\[([^\]]+)\]', product_name)
                    if bracket_brand_match:
                        bracket_brand = bracket_brand_match.group(1)
                        brands.add(bracket_brand)
                    
                    # 기존 브랜드 매칭도 계속 사용
                    product_name_upper = product_name.upper()
                    for brand in common_brands:
                        if brand.upper() in product_name_upper:
                            brands.add(brand)
            
            # 실제로 찾은 브랜드만 반환 (기본 브랜드 목록 제거)
            if not brands:
                return []  # 브랜드를 찾지 못하면 빈 목록 반환
            
            return [{'name': brand, 'code': brand} for brand in sorted(brands)]
            
        except Exception as e:
            print(f"브랜드 검색 중 오류 발생: {e}")
            # 오류 시에도 빈 목록 반환 (실제 데이터가 없으면 브랜드도 없어야 함)
            return []

    def search_products(self, keyword: str, sort_type: str, maker_codes: List[str], limit: int = 5) -> List[Product]:
        """
        컴퓨존에서 제품을 검색합니다 - 실제 사이트 구조 기반으로 최적화된 다단계 검색
        
        Args:
            keyword: 검색할 키워드 (예: "SSD", "RTX 4090")
            sort_type: 정렬 방식 ("sale_order", "price_order" 등)  
            maker_codes: 제조사 필터 코드 리스트
            limit: 반환할 최대 상품 수
            
        Returns:
            List[Product]: 파싱된 상품 객체 리스트
            
        동작 방식:
            1. 메인 검색 페이지 방문으로 세션 설정
            2. 3가지 검색 전략을 순차적으로 시도
            3. 첫 번째 성공한 전략의 결과 반환
            4. 중복 제거 및 제조사 필터링 적용
        """
        try:
            print(f"=== 컴퓨존 제품 검색 시작 ===")
            print(f"검색어: '{keyword}', 제조사 필터: {len(maker_codes)}개, 요청 한도: {limit}개")
            
            # ========== 1단계: 기본 검색 환경 설정 ==========
            # URL 인코딩: 한글 및 특수문자를 URL에서 사용 가능한 형태로 변환
            encoded_keyword = urllib.parse.quote(keyword, encoding='utf-8')
            search_url = f"{self.base_url}?SearchProductKey={encoded_keyword}"
            print(f"검색 URL: {search_url}")
            
            # 메인 검색 페이지 방문: 쿠키 설정 및 세션 초기화를 위해 필요
            try:
                resp = self.session.get(search_url, timeout=10)
                resp.encoding = 'euc-kr'  # 컴퓨존은 EUC-KR 인코딩 사용
                resp.raise_for_status()
                print(f"[OK] 검색 페이지 접근 성공 (상태코드: {resp.status_code})")
            except Exception as e:
                print(f"[ERROR] 검색 페이지 접근 실패: {e}")
                return []
            
            # ========== 2단계: 다중 검색 전략 정의 ==========
            # 실제 사이트 분석 결과를 바탕으로 3가지 검색 전략을 순차적으로 시도
            search_strategies = self._build_search_strategies(keyword, sort_type)
            
            all_products = []
            successful_strategy = None
            
            # ========== 3단계: 검색 전략 순차 실행 ==========
            for strategy_index, strategy in enumerate(search_strategies, 1):
                try:
                    strategy_name = strategy.pop("name")  # 'name' 키는 로깅용, API 호출에서 제외
                    print(f"\n--- 검색 전략 {strategy_index}: '{strategy_name}' 시도 중 ---")
                    
                    # API 호출을 위한 HTTP 헤더 설정
                    headers = self._build_api_headers(search_url)
                    
                    # 실제 API 호출 수행
                    resp = self._call_search_api(strategy, headers)
                    if not resp:
                        print(f"[ERROR] 전략 '{strategy_name}': API 호출 실패")
                        continue
                    
                    # HTML 파싱 및 상품 요소 추출
                    product_items = self._extract_product_elements(resp, strategy_name)
                    if not product_items:
                        print(f"[ERROR] 전략 '{strategy_name}': 상품 요소를 찾을 수 없음")
                        continue
                    
                    # 개별 상품 파싱 및 필터링
                    parsed_products = self._parse_all_products(product_items, maker_codes, keyword, limit)
                    
                    if parsed_products:
                        all_products = parsed_products
                        successful_strategy = strategy_name
                        print(f"[OK] 전략 '{strategy_name}': {len(parsed_products)}개 상품 파싱 성공")
                        break  # 성공한 전략이 있으면 더 이상 시도하지 않음
                    else:
                        print(f"[ERROR] 전략 '{strategy_name}': 유효한 상품을 파싱하지 못함")
                        
                except Exception as e:
                    print(f"[ERROR] 검색 전략 '{strategy_name}' 실행 중 오류: {e}")
                    continue
            
            # ========== 4단계: 결과 정리 및 반환 ==========
            return self._finalize_search_results(all_products, limit, successful_strategy)
            
        except Exception as e:
            print(f"[ERROR] 컴퓨존 검색 전체 실패: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _build_search_strategies(self, keyword: str, sort_type: str) -> List[Dict]:
        """
        검색 전략 리스트를 구성합니다.
        실제 컴퓨존 사이트 분석 결과를 바탕으로 3가지 전략을 정의
        
        Returns:
            List[Dict]: 각 전략의 API 파라미터 딕셔너리
        """
        return [
            # 전략 1: 컴퓨터 부품 카테고리 한정 검색 (가장 정확한 결과)
            {
                "actype": "list",           # API 타입: 리스트 형태 응답
                "SearchType": "small",      # 검색 타입: 소분류 검색
                "SearchText": keyword,      # 실제 검색어
                "PreOrder": sort_type or "sale_order",  # 정렬: 판매순/가격순 등
                "PageCount": "30",          # 페이지당 상품 수
                "StartNum": "0",            # 시작 번호
                "PageNum": "1",             # 페이지 번호
                "ListType": "0",            # 리스트 타입
                "BigDivNo": "4",            # 대분류: 컴퓨터 부품 (사이트 분석으로 확인)
                "MediumDivNo": "",          # 중분류: 비워둠 (전체)
                "DivNo": "",                # 소분류: 비워둠 (전체)
                "MinPrice": "0",            # 최소 가격
                "MaxPrice": "0",            # 최대 가격 (0은 제한 없음)
                "ChkMakerNo": "",           # 제조사 필터 (클라이언트에서 처리)
                "name": "컴퓨터부품_카테고리"  # 로깅용 이름
            },
            # 전략 2: 전체 카테고리 검색 (더 넓은 범위)
            {
                "actype": "list",
                "SearchType": "small",
                "SearchText": keyword,
                "PreOrder": sort_type or "sale_order",
                "PageCount": "30",
                "StartNum": "0",
                "PageNum": "1",
                "ListType": "0",
                "BigDivNo": "",             # 대분류 비워둠 = 전체 카테고리
                "MediumDivNo": "",
                "DivNo": "",
                "MinPrice": "0",
                "MaxPrice": "0",
                "ChkMakerNo": "",
                "name": "전체_카테고리"
            },
            # 전략 3: 통합 검색 (최대 범위, 마지막 수단)
            {
                "actype": "list",
                "SearchType": "total",      # 전체 검색 모드
                "SearchText": keyword,
                "PreOrder": sort_type or "sale_order",
                "PageCount": "30",
                "StartNum": "0",
                "PageNum": "1",
                "ListType": "0",
                "BigDivNo": "",
                "MediumDivNo": "",
                "DivNo": "",
                "MinPrice": "0",
                "MaxPrice": "0",
                "ChkMakerNo": "",
                "name": "통합_검색"
            }
        ]

    def _build_api_headers(self, search_url: str) -> Dict[str, str]:
        """
        API 호출을 위한 HTTP 헤더를 구성합니다.
        실제 브라우저의 AJAX 요청을 모방
        
        Args:
            search_url: 메인 검색 페이지 URL (Referer로 사용)
            
        Returns:
            Dict[str, str]: HTTP 헤더 딕셔너리
        """
        return {
            "Accept": "*/*",                    # 모든 응답 타입 허용
            "Referer": search_url,              # 이전 페이지 URL (중요!)
            "X-Requested-With": "XMLHttpRequest",  # AJAX 요청임을 표시
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Cache-Control": "no-cache",        # 캐시 무시
            "User-Agent": self.session.headers.get('User-Agent', '')  # 기존 User-Agent 유지
        }

    def _call_search_api(self, params: Dict, headers: Dict) -> Optional[requests.Response]:
        """
        실제 검색 API를 호출합니다.
        
        Args:
            params: API 파라미터 딕셔너리
            headers: HTTP 헤더 딕셔너리
            
        Returns:
            requests.Response 또는 None (실패시)
        """
        try:
            resp = self.session.get(
                self.search_api_url,        # https://www.compuzone.co.kr/search/search_list.php
                params=params,
                headers=headers,
                timeout=15
            )
            resp.encoding = 'euc-kr'        # 한글 깨짐 방지
            
            # 응답 유효성 검사
            if resp.status_code != 200:
                print(f"   HTTP 오류: {resp.status_code}")
                return None
                
            if len(resp.text) < 100:
                print(f"   응답 데이터가 너무 짧음: {len(resp.text)}자")
                return None
                
            print(f"   [OK] API 호출 성공 (응답 크기: {len(resp.text)}자)")
            return resp
            
        except Exception as e:
            print(f"   API 호출 예외: {e}")
            return None

    def _extract_product_elements(self, response: requests.Response, strategy_name: str) -> List:
        """
        HTTP 응답에서 상품 HTML 요소들을 추출합니다.
        다양한 CSS 선택자를 시도하여 상품 요소를 찾음
        
        Args:
            response: HTTP 응답 객체
            strategy_name: 전략 이름 (로깅용)
            
        Returns:
            List: BeautifulSoup 상품 요소 리스트
        """
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 컴퓨존 사이트 구조 분석 결과를 바탕으로 다양한 선택자 시도
        # 우선순위 순으로 배치 (가장 확실한 것부터)
        product_selectors = [
            "li.li-obj",                    # 컴퓨존의 기본 상품 리스트 아이템
            ".product-item",                # 일반적인 상품 아이템 클래스
            ".prd-item",                    # 상품 아이템 변형
            ".goods-item",                  # 상품 아이템 다른 표현
            "li[class*='item']",            # 'item'이 포함된 모든 li 요소
            "div[class*='product']",        # 'product'가 포함된 모든 div 요소
            ".item",                        # 범용 아이템 클래스
            "[class*='prd']"                # 'prd'가 포함된 모든 요소
        ]
        
        for selector in product_selectors:
            items = soup.select(selector)
            if items:
                print(f"   [OK] 선택자 '{selector}'로 {len(items)}개 상품 요소 발견")
                return items
                
        print(f"   [ERROR] 모든 선택자에서 상품 요소를 찾지 못함")
        return []

    def _parse_all_products(self, product_items: List, maker_codes: List[str], 
                          keyword: str, limit: int) -> List[Product]:
        """
        추출된 상품 요소들을 개별적으로 파싱합니다.
        
        Args:
            product_items: BeautifulSoup 상품 요소 리스트
            maker_codes: 제조사 필터 코드
            keyword: 검색 키워드
            limit: 최대 상품 수
            
        Returns:
            List[Product]: 파싱된 상품 객체 리스트
        """
        all_products = []
        parsed_count = 0
        failed_count = 0
        
        print(f"   상품 파싱 시작: {len(product_items)}개 요소 처리")
        
        for index, item in enumerate(product_items, 1):
            try:
                # 개별 상품 파싱 (옵션 상품 포함)
                parsed_products = self._parse_product_item_with_options(item, maker_codes, keyword)
                
                if parsed_products:
                    all_products.extend(parsed_products)
                    parsed_count += len(parsed_products)
                    
                    # 로그 출력 (너무 많으면 5개마다)
                    if parsed_count <= 5 or parsed_count % 5 == 0:
                        print(f"   파싱 진행: {parsed_count}개 상품 완료 ({index}/{len(product_items)} 요소)")
                else:
                    failed_count += 1
                
                # 충분한 상품을 확보했으면 중단
                if len(all_products) >= limit * 3:  # 여유분 확보
                    print(f"   충분한 상품 확보: {len(all_products)}개, 파싱 중단")
                    break
                    
            except Exception as parse_error:
                failed_count += 1
                # 상세 에러는 디버그 모드에서만 출력
                if failed_count <= 3:  # 처음 3개 에러만 출력
                    print(f"   파싱 실패 #{failed_count}: {str(parse_error)[:50]}...")
                continue
        
        print(f"   파싱 완료: 성공 {parsed_count}개, 실패 {failed_count}개")
        return all_products

    def _finalize_search_results(self, all_products: List[Product], limit: int, 
                               successful_strategy: Optional[str]) -> List[Product]:
        """
        검색 결과를 최종 정리합니다.
        중복 제거, 필터링, 정렬 등을 수행
        
        Args:
            all_products: 파싱된 모든 상품
            limit: 최대 반환 상품 수
            successful_strategy: 성공한 검색 전략 이름
            
        Returns:
            List[Product]: 최종 정리된 상품 리스트
        """
        if not all_products:
            print("[ERROR] 모든 검색 전략 실패 - 상품을 찾을 수 없음")
            return []
        
        print(f"\n=== 검색 결과 정리 ===")
        print(f"성공 전략: {successful_strategy}")
        print(f"파싱된 총 상품: {len(all_products)}개")
        
        # 중복 제거: 상품명 기준
        unique_products = []
        seen_names = set()
        duplicate_count = 0
        
        for product in all_products:
            # 유효성 검사
            if not product or not product.name:
                continue
                
            # 중복 검사
            if product.name in seen_names:
                duplicate_count += 1
                continue
                
            unique_products.append(product)
            seen_names.add(product.name)
        
        print(f"중복 제거: {duplicate_count}개 제거, {len(unique_products)}개 유니크 상품")
        
        # 최종 개수 제한
        final_products = unique_products[:limit]
        
        print(f"최종 반환: {len(final_products)}개 상품")
        print("=== 컴퓨존 검색 완료 ===\n")
        
        return final_products

    def _parse_product_item_with_options(self, item, maker_codes: List[str], keyword: str) -> List[Product]:
        """제품 아이템을 파싱하고 검색어에 맞는 옵션만 필터링합니다."""
        try:
            # 제품명 추출
            product_name_tag = item.select_one(".prd_info_name.prdTxt, .prd_info_name")
            if not product_name_tag:
                return []
                
            base_product_name = product_name_tag.get_text(strip=True)
            if not base_product_name:
                return []
            
            # 브랜드 필터링 (개선된 동적 매칭 방식)
            if maker_codes:
                brand_found = self._check_brand_match(base_product_name, maker_codes)
                if not brand_found:
                    return []
            
            # 검색어에서 용량 정보 추출
            capacity_filter = self._extract_capacity_from_keyword(keyword)
            
            # 옵션 섹션 확인
            option_wrap = item.select_one(".prd_option_wrap")
            if option_wrap:
                return self._parse_product_options_filtered(item, base_product_name, capacity_filter)
            else:
                # 옵션이 없는 경우 기존 방식으로 처리하되 용량 필터링 적용
                product = self._parse_single_product_filtered(item, base_product_name, capacity_filter)
                return [product] if product else []
            
        except Exception as e:
            print(f"제품 파싱 중 오류: {e}")
            return []

    def _extract_capacity_from_keyword(self, keyword: str) -> Optional[str]:
        """검색어에서 용량 정보를 추출합니다."""
        keyword_upper = keyword.upper()
        
        # 용량 패턴 매칭 (숫자 + 단위)
        capacity_patterns = [
            r'(\d+)\s*TB',
            r'(\d+)\s*GB',
            r'(\d+)\s*MB'
        ]
        
        for pattern in capacity_patterns:
            match = re.search(pattern, keyword_upper)
            if match:
                number = match.group(1)
                if 'TB' in keyword_upper:
                    return f"{number}TB"
                elif 'GB' in keyword_upper:
                    return f"{number}GB"
                elif 'MB' in keyword_upper:
                    return f"{number}MB"
        
        return None

    def _parse_product_options_filtered(self, item, base_product_name: str, capacity_filter: Optional[str]) -> List[Product]:
        """제품 옵션들을 파싱하고 용량 필터를 적용합니다."""
        products = []
        
        try:
            option_items = item.select(".prd_option")
            
            for option_item in option_items:
                # 옵션명 추출 (두 가지 구조 모두 지원)
                option_name_tag = option_item.select_one(".op_name")  # HDD 타입
                opt_detail_tag = option_item.select_one(".opt_name")  # SSD 타입
                
                option_name = ""
                option_detail = ""
                
                if option_name_tag:
                    # HDD 타입 (op_name에 용량 정보)
                    option_name = option_name_tag.get_text(strip=True)
                elif opt_detail_tag:
                    # SSD 타입 (opt_name에 상세 정보)
                    option_detail = opt_detail_tag.get_text(strip=True)
                    option_name = option_detail  # 임시로 사용
                else:
                    continue
                
                # 용량 필터링 적용
                if capacity_filter:
                    if not self._matches_capacity_filter(option_name, capacity_filter):
                        continue
                
                # 세부 옵션 영역 확인 (.op_list_area)
                op_list_area = option_item.select_one(".op_list_area")
                if op_list_area:
                    # 세부 옵션들이 있는 경우 (예: 4TB 개별/5팩/10팩)
                    sub_options = op_list_area.select(".op_list")
                    for sub_opt in sub_options:
                        sub_product = self._parse_sub_option(sub_opt, base_product_name, option_name, item)
                        if sub_product:
                            products.append(sub_product)
                else:
                    # 세부 옵션이 없는 일반적인 경우
                    product = self._parse_regular_option(option_item, base_product_name, option_name, item)
                    if product:
                        products.append(product)
                
        except Exception as e:
            print(f"옵션 파싱 중 오류: {e}")
        
        return products

    def _parse_sub_option(self, sub_opt, base_product_name: str, option_name: str, item) -> Optional[Product]:
        """세부 옵션을 파싱합니다 (예: 4TB 개별/5팩/10팩)."""
        try:
            # 세부 옵션명 추출 (.opt_name)
            sub_opt_name_tag = sub_opt.select_one(".opt_name")
            if not sub_opt_name_tag:
                return None
                
            sub_opt_name = sub_opt_name_tag.get_text(strip=True)
            
            # 제품 번호 추출 (세부 옵션에서)
            product_link = ""
            checkbox = sub_opt.select_one(".SelGroupProductNo")
            if checkbox:
                product_no = checkbox.get('value')
                if product_no:
                    product_link = f"https://www.compuzone.co.kr/product/product_detail.htm?ProductNo={product_no}"
            
            # 세부 옵션 가격 추출
            sub_price_tag = sub_opt.select_one(".op_price .f_black")
            if not sub_price_tag:
                # 품절인지 확인
                if "품절" in sub_opt.get_text() or "재입고" in sub_opt.get_text():
                    formatted_price = "품절"
                else:
                    return None
            else:
                sub_price_text = sub_price_tag.get_text(strip=True)
                formatted_price = self._format_price(sub_price_text)
                if formatted_price in ["가격 정보 없음", "가격 문의"]:
                    formatted_price = "품절"
            
            # 세부 사양 추출
            option_specs = []
            
            # 1. 메인 옵션명 추가
            option_specs.append(option_name)
            
            # 2. 세부 사양 추가 (괄호 안의 내용)
            spec_match = re.search(r'\(([^)]+)\)', sub_opt_name)
            if spec_match:
                detailed_specs = spec_match.group(1)
                option_specs.append(detailed_specs)
            
            # 3. 팩 정보 추가
            if '[5PACK]' in sub_opt_name or '5PACK' in sub_opt_name:
                option_specs.append("5개 팩")
            elif '[10PACK]' in sub_opt_name or '10PACK' in sub_opt_name:
                option_specs.append("10개 팩")
            
            # 4. 기본 제품 사양 추가
            base_specs = self._extract_base_product_specs(item)
            if base_specs:
                option_specs.extend(base_specs[:1])  # 최대 1개만
            
            # 제품명 생성
            pack_info = ""
            if '[5PACK]' in sub_opt_name or '5PACK' in sub_opt_name:
                pack_info = " (5개 팩)"
            elif '[10PACK]' in sub_opt_name or '10PACK' in sub_opt_name:
                pack_info = " (10개 팩)"
            
            full_product_name = f"{base_product_name} {option_name}{pack_info}"
            
            # 사양 정리
            final_specs = " / ".join(option_specs) if option_specs else "컴퓨존 상품"
            
            return Product(
                name=full_product_name,
                price=formatted_price,
                specifications=final_specs,
                product_link=product_link,
                site="컴퓨존"
            )
            
        except Exception as e:
            print(f"세부 옵션 파싱 중 오류: {e}")
            return None

    def _parse_regular_option(self, option_item, base_product_name: str, option_name: str, item) -> Optional[Product]:
        """일반적인 옵션을 파싱합니다."""
        try:
            # 제품 번호 추출 (메인 제품에서)
            product_link = ""
            main_link = item.select_one(".prd_info_name")
            if main_link:
                href = main_link.get('href')
                if href:
                    if href.startswith('http'):
                        product_link = href
                    elif href.startswith('/'):
                        product_link = f"https://www.compuzone.co.kr{href}"
                    elif href.startswith('../'):
                        product_link = f"https://www.compuzone.co.kr/{href.replace('../', '')}"
                    else:
                        product_link = f"https://www.compuzone.co.kr/{href}"
            
            # 옵션 가격 추출
            option_price_tag = option_item.select_one(".op_price .f_black, .op_price span")
            if not option_price_tag:
                return None
                
            option_price_text = option_price_tag.get_text(strip=True)
            
            # 범위 가격 처리 (예: "146,000원~ 1,416,200원")
            if '~' in option_price_text:
                # 범위 가격의 첫 번째 가격 사용
                first_price = option_price_text.split('~')[0].strip()
                formatted_price = self._format_price(first_price)
                if formatted_price not in ["가격 정보 없음", "가격 문의"]:
                    formatted_price = formatted_price.replace("원", "원부터")
                else:
                    return None
            else:
                # 일반 가격 처리
                formatted_price = self._format_price(option_price_text)
                if formatted_price in ["가격 정보 없음", "가격 문의"]:
                    if "품절" in option_item.get_text():
                        formatted_price = "품절"
                    else:
                        return None
            
            # 옵션 상세 사양 추출
            option_specs = []
            
            # 1. 옵션명 추가
            if option_name:
                option_specs.append(option_name)
            
            # 2. 세부 사양 추출 (SSD/HDD 타입별)
            opt_detail_tag = option_item.select_one(".opt_name")
            if opt_detail_tag:
                additional_detail = opt_detail_tag.get_text(strip=True)
                spec_match = re.search(r'\(([^)]+)\)', additional_detail)
                if spec_match:
                    detailed_specs = spec_match.group(1)
                    option_specs.append(detailed_specs)
            
            # 3. 기본 제품 사양 추가
            base_specs = self._extract_base_product_specs(item)
            if base_specs:
                option_specs.extend(base_specs[:2])  # 최대 2개만
            
            # 제품명 생성
            full_product_name = f"{base_product_name} {option_name}"
            
            # 사양 정리
            final_specs = " / ".join(option_specs) if option_specs else "컴퓨존 상품"
            
            return Product(
                name=full_product_name,
                price=formatted_price,
                specifications=final_specs,
                product_link=product_link,
                site="컴퓨존"
            )
            
        except Exception as e:
            print(f"일반 옵션 파싱 중 오류: {e}")
            return None

    def _matches_capacity_filter(self, option_name: str, capacity_filter: str) -> bool:
        """옵션명이 용량 필터와 일치하는지 확인합니다."""
        option_upper = option_name.upper()
        filter_upper = capacity_filter.upper()
        
        # 정확한 패턴 매칭 (단어 경계 고려)
        # 예: "8GB"는 "128GB"와 매칭되지 않도록
        filter_pattern = r'\b' + re.escape(filter_upper) + r'\b'
        if re.search(filter_pattern, option_upper):
            return True
        
        # 숫자와 단위를 분리해서 정확히 매칭
        filter_match = re.search(r'(\d+)\s*(TB|GB|MB)', filter_upper)
        option_match = re.search(r'(\d+)\s*(TB|GB|MB)', option_upper)
        
        if filter_match and option_match:
            filter_num = filter_match.group(1)
            filter_unit = filter_match.group(2)
            option_num = option_match.group(1)
            option_unit = option_match.group(2)
            
            # 숫자와 단위가 모두 일치해야 함
            if filter_num == option_num and filter_unit == option_unit:
                return True
        
        # 단위 변환 (1TB = 1024GB)
        if filter_match and option_match:
            filter_num = int(filter_match.group(1))
            filter_unit = filter_match.group(2)
            option_num = int(option_match.group(1))
            option_unit = option_match.group(2)
            
            # TB를 GB로 변환해서 비교
            filter_gb = filter_num * 1024 if filter_unit == 'TB' else filter_num
            option_gb = option_num * 1024 if option_unit == 'TB' else option_num
            
            if filter_gb == option_gb:
                return True
        
        return False

    def _parse_single_product_filtered(self, item, product_name: str, capacity_filter: Optional[str]) -> Optional[Product]:
        """단일 제품을 파싱하고 용량 필터를 적용합니다."""
        try:
            # 용량 필터링 적용
            if capacity_filter:
                if not self._matches_capacity_filter(product_name, capacity_filter):
                    return None
            
            # 제품 링크 추출
            product_link = ""
            main_link = item.select_one(".prd_info_name")
            if main_link:
                href = main_link.get('href')
                if href:
                    if href.startswith('http'):
                        product_link = href
                    elif href.startswith('/'):
                        product_link = f"https://www.compuzone.co.kr{href}"
                    elif href.startswith('../'):
                        product_link = f"https://www.compuzone.co.kr/{href.replace('../', '')}"
                    else:
                        product_link = f"https://www.compuzone.co.kr/{href}"
            
            # 기존 단일 제품 파싱 로직
            price_text = "품절"
            price_selectors = [
                ".prd_price .number",
                ".prd_price .price", 
                ".price_sect .number",
                ".price .number",
                ".prd_price"
            ]
            
            for selector in price_selectors:
                price_tag = item.select_one(selector)
                if price_tag:
                    price_text = price_tag.get_text(strip=True)
                    break
            
            formatted_price = self._format_price(price_text)
            if formatted_price in ["가격 정보 없음", "가격 문의"]:
                formatted_price = "품절"
            
            specifications = self._extract_base_product_specs(item)
            final_specs_text = " / ".join(specifications) if specifications else "컴퓨존 상품"
            deduplicated_specs = self._smart_deduplicate_specs(final_specs_text)
            
            return Product(
                name=product_name, 
                price=formatted_price, 
                specifications=deduplicated_specs,
                product_link=product_link,
                site="컴퓨존"
            )
            
        except Exception as e:
            print(f"단일 제품 파싱 중 오류: {e}")
            return None

    def _parse_product_item(self, item, maker_codes: List[str]) -> Optional[Product]:
        """제품 아이템을 파싱합니다."""
        try:
            # 제품명 추출
            product_name_tag = item.select_one(".prd_info_name.prdTxt, .prd_info_name")
            if not product_name_tag:
                return None
                
            product_name = product_name_tag.get_text(strip=True)
            if not product_name:
                return None
            
            # 브랜드 필터링 (컴퓨존 [브랜드] 형식 고려)
            if maker_codes:
                brand_found = False
                
                # [브랜드] 형식에서 브랜드 추출
                bracket_brand_match = re.search(r'\[([^\]]+)\]', product_name)
                if bracket_brand_match:
                    bracket_brand = bracket_brand_match.group(1).strip()
                    
                    # 브랜드 매칭 검사 (개선된 동적 방식)
                    brand_found = self._check_brand_match(product_name, maker_codes)
                    if not brand_found:
                        return None
            
            # 가격 추출 - 여러 가능한 선택자 시도
            price_text = "품절"  # 기본값을 품절로 변경
            price_selectors = [
                ".prd_price .number",
                ".prd_price .price", 
                ".price_sect .number",
                ".price .number",
                ".prd_price"
            ]
            
            for selector in price_selectors:
                price_tag = item.select_one(selector)
                if price_tag:
                    price_text = price_tag.get_text(strip=True)
                    break
            
            # 가격 정리
            formatted_price = self._format_price(price_text)
            if formatted_price in ["가격 정보 없음", "가격 문의"]:
                # 숫자 가격이 없으면 구매 불가능한 상태로 간주
                formatted_price = "품절"
            
            # 사양 정보 추출 시도 (다양한 방법으로)
            specifications = []
            
            # 1. 제품명에서 주요 사양 추출
            name_specs = self._extract_specs_from_name(product_name)
            if name_specs:
                specifications.extend(name_specs)
            
            # 2. .prd_subTxt에서 상세 사양 정보 추출 (가장 정확한 방법)
            prd_subTxt = item.select_one(".prd_subTxt")
            if prd_subTxt:
                spec_text = prd_subTxt.get_text(strip=True)
                if spec_text and len(spec_text) > 10:
                    # 불필요한 텍스트 제거 후 사양 정보 추가
                    clean_spec = re.sub(r'\s+', ' ', spec_text)
                    specifications.append(clean_spec[:200])  # 너무 길면 자르기
            
            # 3. .prd_subTxt가 없으면 .prd_info에서 추출 (기존 방법)
            if not any('/' in spec for spec in specifications):
                prd_info = item.select_one(".prd_info")
                if prd_info:
                    info_text = prd_info.get_text(separator=' | ', strip=True)
                    parts = info_text.split(' | ')
                    
                    if len(parts) > 3:
                        spec_part = parts[3].strip()
                        if spec_part and len(spec_part) > 10 and not any(skip in spec_part for skip in ['토스', '확정발주', '입고지연']):
                            spec_items = [s.strip() for s in spec_part.split('/') if s.strip() and len(s.strip()) > 2]
                            if spec_items:
                                selected_specs = spec_items[:5]
                                specifications.append(' / '.join(selected_specs))
            
            # 4. 기본값 설정
            if not specifications:
                specifications.append("컴퓨존 상품")
            
            # 5. 최종 사양 스마트 중복 제거
            final_specs_text = " / ".join(specifications)
            deduplicated_specs = self._smart_deduplicate_specs(final_specs_text)
            
            return Product(
                name=product_name, 
                price=formatted_price, 
                specifications=deduplicated_specs,
                product_link="",
                site="컴퓨존"
            )
            
        except Exception as e:
            print(f"제품 파싱 중 오류: {e}")
            return None

    def _extract_base_product_specs(self, item) -> List[str]:
        """제품의 기본 사양 정보를 추출합니다."""
        specifications = []
        
        # 1. .prd_subTxt에서 상세 사양 정보 추출 (가장 정확한 방법)
        prd_subTxt = item.select_one(".prd_subTxt")
        if prd_subTxt:
            spec_text = prd_subTxt.get_text(strip=True)
            if spec_text and len(spec_text) > 10:
                # 불필요한 텍스트 제거 후 사양 정보 추가
                clean_spec = re.sub(r'\s+', ' ', spec_text)
                spec_parts = [part.strip() for part in clean_spec.split('/') if part.strip()]
                specifications.extend(spec_parts[:3])  # 처음 3개만
        
        # 2. .prd_subTxt가 없으면 .prd_info에서 추출 (기존 방법)
        if not specifications:
            prd_info = item.select_one(".prd_info")
            if prd_info:
                info_text = prd_info.get_text(separator=' | ', strip=True)
                parts = info_text.split(' | ')
                
                if len(parts) > 3:
                    spec_part = parts[3].strip()
                    if spec_part and len(spec_part) > 10 and not any(skip in spec_part for skip in ['토스', '확정발주', '입고지연']):
                        spec_items = [s.strip() for s in spec_part.split('/') if s.strip() and len(s.strip()) > 2]
                        if spec_items:
                            specifications.extend(spec_items[:3])
        
        return specifications

    def _extract_specs_from_name(self, product_name: str) -> List[str]:
        """제품명에서 주요 사양 정보를 간단히 추출합니다."""
        specs = []
        name_upper = product_name.upper()
        
        # 1. 용량 정보 추출 (GB, TB)
        capacity_matches = re.findall(r'(\d+[KMGT]?B)', name_upper)
        for capacity in capacity_matches:
            # GPU인 경우 VRAM으로 표시
            if any(keyword in name_upper for keyword in ['RTX', 'GTX', 'RX', 'RADEON', 'GEFORCE']):
                specs.append(f"VRAM {capacity}")
                break  # GPU는 하나의 VRAM만
            else:
                specs.append(capacity)
                break  # 저장장치도 하나의 용량만
        
        # 2. 제품 시리즈 추출 (RTX, GTX, RX 등)
        series_patterns = [
            r'(RTX \d+)', r'(GTX \d+)', r'(RX \d+)', r'(ARC A\d+)',
            r'(I\d-\d+K?F?)', r'(RYZEN \d+ \d+X?)'
        ]
        for pattern in series_patterns:
            match = re.search(pattern, name_upper)
            if match:
                specs.append(match.group(1))
                break  # 하나의 시리즈만
        
        # 3. 메모리 타입 추출
        memory_types = ['DDR5', 'DDR4', 'GDDR6X', 'GDDR6', 'HBM3', 'HBM2']
        for mem_type in memory_types:
            if mem_type in name_upper:
                specs.append(mem_type)
                break  # 하나의 메모리 타입만
        
        return specs[:3]  # 최대 3개만 반환

    def _smart_deduplicate_specs(self, specs_text: str) -> str:
        """스마트 사양 중복 제거 - 의미적 유사성 기반"""
        if not specs_text:
            return specs_text
        
        parts = [part.strip() for part in specs_text.split(" / ") if part.strip()]
        if len(parts) <= 1:
            return specs_text
        
        unique_parts = []
        
        for part in parts:
            is_duplicate = False
            
            for i, existing_part in enumerate(unique_parts):
                if self._is_semantic_duplicate(part, existing_part):
                    # 더 정보가 많은 것을 선택
                    if len(part) > len(existing_part):
                        unique_parts[i] = part
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                unique_parts.append(part)
        
        return " / ".join(unique_parts)
    
    def _is_semantic_duplicate(self, text1: str, text2: str) -> bool:
        """두 텍스트가 의미적으로 중복인지 판단"""
        t1, t2 = text1.lower().strip(), text2.lower().strip()
        
        # 1. 완전 동일
        if t1 == t2:
            return True
        
        # 2. 숫자+단위 패턴으로 용량 비교
        def extract_capacity(text):
            match = re.search(r'(\d+)\s*([KMGT]?B?)', text.upper())
            if match:
                number, unit = match.groups()
                if unit in ['G', 'K', 'M', 'T']:
                    unit = unit + 'B'
                return (number, unit)
            return None
        
        cap1, cap2 = extract_capacity(t1), extract_capacity(t2)
        
        # 같은 용량의 메모리/VRAM 정보면 중복
        if cap1 and cap2 and cap1 == cap2:
            has_mem1 = any(kw in t1 for kw in ['vram', 'memory', '메모리', 'gb', 'tb'])
            has_mem2 = any(kw in t2 for kw in ['vram', 'memory', '메모리', 'gb', 'tb'])
            if has_mem1 and has_mem2:
                return True
        
        # 3. 제품 시리즈 중복 (RTX 5080 등)
        def extract_series(text):
            match = re.search(r'(RTX|GTX|RX|ARC)\s*(\d+)', text.upper())
            return match.groups() if match else None
        
        series1, series2 = extract_series(t1), extract_series(t2)
        if series1 and series2 and series1 == series2:
            return True
        
        return False

    def _is_generic_term(self, brand_name: str) -> bool:
        """일반적인 용어나 의미없는 브랜드명인지 유연하게 확인합니다."""
        if not brand_name or len(brand_name.strip()) <= 1:
            return True
        
        brand_lower = brand_name.lower().strip()
        
        # 1. 숫자로만 구성된 경우
        if re.match(r'^\d+$', brand_name):
            return True
        
        # 2. 의미없는 기호나 문자
        if brand_name in ['', ' ', '-', '_', '.', '/', '\\', '?', '!', '*']:
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
            if re.search(pattern, brand_lower):
                return True
        
        # 4. 브랜드가 아닌 일반 명사나 형용사일 가능성이 높은 경우
        # 한글로만 구성되고 특정 패턴을 가진 경우
        if re.match(r'^[가-힣]+$', brand_name):
            # 너무 일반적인 단어들은 제외 (길이 기반)
            if len(brand_name) <= 2:  # 2글자 이하 한글은 대부분 일반 명사
                return True
            # 조사나 어미가 포함된 경우
            if brand_name.endswith(('에서', '으로', '부터', '까지', '에게', '에서')):
                return True
        
        return False

    def get_unique_products(self, keyword: str, maker_codes: List[str]) -> List[Product]:
        """danawa와 호환되도록 하지만 컴퓨존은 단일 검색만 수행"""
        products = self.search_products(keyword, "sale_order", maker_codes, limit=10)
        
        # 중복 제거
        unique_products = []
        seen_names = set()
        for product in products:
            if product.name not in seen_names:
                unique_products.append(product)
                seen_names.add(product.name)
        
        return unique_products

