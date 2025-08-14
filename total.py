# -*- coding: utf-8 -*-
"""
통합 쇼핑몰 크롤러
- 다나와, 컴퓨존, 가이드컴 통합
- 함수 충돌 방지를 위한 모듈화 설계
"""

import os
import re
import time
import random
import requests
import urllib.parse
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from difflib import SequenceMatcher

# ============================================================================
# 공통 데이터 클래스
# ============================================================================

@dataclass
class Product:
    name: str
    price: str
    specifications: str
    site: str  # 'danawa', 'compuzone', 'guidecom'

@dataclass
class ProductGroup:
    """비슷한 제품들을 그룹핑"""
    representative_name: str  # 대표 제품명
    products: List[Product]   # 같은 그룹의 제품들

# ============================================================================
# 다나와 파서 (네임스페이스 분리)
# ============================================================================

class DanawaParser:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        self.base_url = "https://search.danawa.com/dsearch.php"

    def get_search_options(self, keyword: str) -> List[Dict[str, str]]:
        """다나와 제조사 옵션 추출"""
        params = {'query': keyword}
        try:
            response = self.session.get(self.base_url, params=params)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 1. 정확한 방법 시도
            options = self._get_options_strictly(soup)
            if options:
                return options[:10]  # 최대 10개
                
            # 2. 대안 방법
            return self._get_options_fallback(soup)[:10]
            
        except Exception as e:
            print(f"다나와 옵션 추출 실패: {e}")
            return []

    def _get_options_strictly(self, soup) -> List[Dict[str, str]]:
        """정확한 제조사 옵션 추출"""
        options = []
        try:
            # 제조사 필터 영역에서 추출
            brand_elements = soup.select('.filter_brand .filter_item input[type="checkbox"]')
            for elem in brand_elements:
                brand_name = elem.get('data-brand-name') or elem.get('value', '')
                if brand_name and len(brand_name.strip()) > 0:
                    options.append({'name': brand_name.strip(), 'code': brand_name.strip()})
        except:
            pass
        return options

    def _get_options_fallback(self, soup) -> List[Dict[str, str]]:
        """대안 제조사 옵션 추출"""
        return [
            {'name': '삼성전자', 'code': '삼성전자'},
            {'name': 'LG전자', 'code': 'LG전자'},
            {'name': 'ASUS', 'code': 'ASUS'},
            {'name': 'MSI', 'code': 'MSI'}
        ]

    def search_products(self, keyword: str, sort_type: str, maker_codes: List[str], limit: int = 5) -> List[Product]:
        """다나와 제품 검색"""
        try:
            params = {
                'query': keyword,
                'sort': 'price',  # 가격순 정렬
                'limit': limit
            }
            
            if maker_codes:
                params['brand'] = ','.join(maker_codes)
            
            response = self.session.get(self.base_url, params=params)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            products = []
            product_items = soup.select('.prod_item, .product_list > li, .search_result .item')[:limit]
            
            for item in product_items:
                product = self._parse_danawa_product(item, maker_codes)
                if product:
                    products.append(product)
                    
            return products
            
        except Exception as e:
            print(f"다나와 검색 실패: {e}")
            return []

    def _parse_danawa_product(self, item, maker_codes: List[str]) -> Optional[Product]:
        """다나와 제품 파싱"""
        try:
            # 제품명 추출
            name_selectors = ['.prod_name a', '.product_name', '.name a', 'h3 a']
            name = ""
            for selector in name_selectors:
                name_elem = item.select_one(selector)
                if name_elem:
                    name = name_elem.get_text(strip=True)
                    break
            
            if not name:
                return None
            
            # 가격 추출
            price_selectors = ['.price_sect em', '.price em', '.prod_pricelist .price', '.price_area .price']
            price = "품절"
            for selector in price_selectors:
                price_elem = item.select_one(selector)
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    # 숫자만 추출
                    numbers = re.findall(r'\d+', price_text.replace(',', ''))
                    if numbers:
                        price = f"{int(''.join(numbers)):,}원"
                        break
            
            # 사양 추출
            spec_selectors = ['.spec_list', '.prod_spec', '.product_spec']
            specs = "다나와 상품"
            for selector in spec_selectors:
                spec_elem = item.select_one(selector)
                if spec_elem:
                    specs = spec_elem.get_text(strip=True)[:100] + "..."
                    break
            
            return Product(
                name=name,
                price=price,
                specifications=specs,
                site="다나와"
            )
            
        except Exception:
            return None

    def _extract_manufacturer(self, product_name: str) -> Optional[str]:
        """제품명에서 제조사 추출"""
        if not product_name:
            return None
        
        # 대괄호 제거 및 정리
        text = re.sub(r"\[[^\]]+\]", " ", product_name)
        text = re.sub(r"\s+", " ", text).strip()
        words = text.split()
        
        if not words:
            return None
            
        # 건너뛸 단어들
        skip = {"신제품", "신상품", "공식인증", "병행수입", "벌크", "정품", "할인", "특가"}
        
        i = 0
        while i < len(words):
            word = words[i]
            if word not in skip and not any(skip_word in word for skip_word in skip):
                break
            i += 1
            
        if i >= len(words):
            return None
            
        manufacturer = words[i]
        
        # 2단어 브랜드 결합
        if i + 1 < len(words):
            pair = f"{manufacturer} {words[i+1]}"
            normalized_pair = self._normalize_brand(pair)
            if normalized_pair in {"western digital", "tp link", "g skill"}:
                manufacturer = pair
                
        return manufacturer

    def _normalize_brand(self, text: str) -> str:
        """브랜드명 정규화"""
        t = (text or "").lower()
        t = re.sub(r"[\s._/-]+", " ", t).strip()
        aliases = {
            "wd": "western digital",
            "웨스턴 디지털": "western digital",
            "에이수스": "asus",
            "기가바이트": "gigabyte",
            "삼성": "삼성전자",
            "samsung": "삼성전자",
        }
        return aliases.get(t, t)

    def _filter_by_maker(self, product: Product, maker_codes: List[str]) -> bool:
        """제조사 코드로 제품 필터링"""
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
        return False

    def get_unique_products(self, keyword: str, maker_codes: List[str]) -> List[Product]:
        """다나와 고유 제품 검색"""
        products = self.search_products(keyword, "price", maker_codes, limit=20)
        # 제조사 필터링 적용
        filtered_products = []
        for product in products:
            if self._filter_by_maker(product, maker_codes):
                filtered_products.append(product)
        return filtered_products[:10]

# ============================================================================
# 컴퓨존 파서 (기존 코드 수정하여 site 필드 추가)
# ============================================================================

class CompuzoneParser:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        self.base_url = "https://www.compuzone.co.kr/search/search.htm"
        self.search_api_url = "https://www.compuzone.co.kr/search/search_list.php"

    def get_search_options(self, keyword: str) -> List[Dict[str, str]]:
        """컴퓨존에서 검색 결과를 통해 브랜드를 추출합니다."""
        try:
            # 간단한 방법: 실제 제품 검색 후 제품명에서 브랜드 추출
            return self._extract_brands_from_search_results(keyword)
        except Exception as e:
            print(f"컴퓨존 브랜드 검색 중 오류 발생: {e}")
            return []

    def _extract_brands_from_search_results(self, keyword: str) -> List[Dict[str, str]]:
        """실제 검색 결과에서 브랜드를 추출합니다 (간단한 방법)."""
        try:
            # 기본 제품 검색 (제조사 필터링 없이)
            products = self.search_products(keyword, "sale_order", [], limit=50)
            
            # 제품명에서 브랜드 추출
            brands_found = {}  # {브랜드명: 개수} 형태로 저장
            
            for product in products:
                # [브랜드] 형식 추출
                bracket_match = re.search(r'\[([^\]]+)\]', product.name)
                if bracket_match:
                    brand_name = bracket_match.group(1).strip()
                    if len(brand_name) > 1:  # 너무 짧은 것 제외
                        brands_found[brand_name] = brands_found.get(brand_name, 0) + 1
            
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
            
            return result[:15]  # 최대 15개까지
            
        except Exception as e:
            print(f"브랜드 추출 실패: {e}")
            return []

    def search_products(self, keyword: str, sort_type: str, maker_codes: List[str], limit: int = 5) -> List[Product]:
        """컴퓨존에서 제품을 검색합니다."""
        try:
            # URL 인코딩된 검색어
            encoded_keyword = urllib.parse.quote(keyword, encoding='utf-8')
            search_url = f"{self.base_url}?SearchProductKey={encoded_keyword}"
            
            # 검색 페이지 접근
            resp = self.session.get(search_url, timeout=10)
            resp.encoding = 'utf-8'
            resp.raise_for_status()
            
            # API 파라미터 설정 (컴퓨터부품 카테고리로 제한)
            params = {
                "actype": "list",
                "SearchType": "small",
                "SearchText": keyword,
                "PreOrder": sort_type if sort_type else "sale_order",
                "PageCount": str(min(limit * 2, 100)),
                "StartNum": "0",
                "PageNum": "1",
                "ListType": "0",
                "BigDivNo": "4",  # 컴퓨터부품 카테고리
                "MediumDivNo": "",
                "DivNo": "",
                "MinPrice": "0",
                "MaxPrice": "0",
                "ChkMakerNo": ""  # 서버 필터링 대신 클라이언트 필터링 사용
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
            
            products = []
            product_items = soup.select("li.li-obj")
            
            for item in product_items:
                product = self._parse_compuzone_product(item, maker_codes)
                if product:
                    products.append(product)
                    if len(products) >= limit:
                        break
            
            return products
            
        except Exception as e:
            print(f"컴퓨존 제품 검색 중 오류 발생: {e}")
            return []

    def _parse_compuzone_product(self, item, maker_codes: List[str]) -> Optional[Product]:
        """컴퓨존 제품 아이템을 파싱합니다."""
        try:
            # 제품명 추출
            product_name_tag = item.select_one(".prd_info_name.prdTxt, .prd_info_name")
            if not product_name_tag:
                return None
                
            product_name = product_name_tag.get_text(strip=True)
            if not product_name:
                return None
            
            # 브랜드 필터링
            if maker_codes:
                brand_found = False
                bracket_brand_match = re.search(r'\[([^\]]+)\]', product_name)
                if bracket_brand_match:
                    bracket_brand = bracket_brand_match.group(1).strip()
                    
                    for code in maker_codes:
                        if code.isdigit():
                            known_brand_names = {
                                '2': '삼성전자', '24': 'Western Digital', '25': 'SEAGATE',
                                '99': 'HP', '4629': '레노버', '10219': 'SEBAP', 
                                '439': '동화', '15947': 'HPE', '1419': 'G.SKILL',
                                '3400': 'ADATA', '6348': 'Crucial', '18': 'Kingston',
                                '763': 'Corsair', '1046': 'Patriot',
                                # HTML 체크박스에서 확인된 RTX 5090 제조사들
                                '14': 'GIGABYTE', '9': 'ASUS', '475': 'MSI',
                                '3169': 'MANLI', '1111': 'PNY', '8842': 'PALIT',
                                '2416': 'ZOTAC', '8231': 'Thermal grizzly', '6238': 'INNO3D',
                                '32': 'GAINWARD'
                            }
                            expected_brand = known_brand_names.get(code, '')
                            if expected_brand and bracket_brand.upper() == expected_brand.upper():
                                brand_found = True
                                break
                        elif code.upper() == bracket_brand.upper():
                            brand_found = True
                            break
                        elif bracket_brand.upper() in code.upper() or code.upper() in bracket_brand.upper():
                            brand_found = True
                            break
                
                if not brand_found:
                    return None
            
            # 가격 추출
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
            
            # 가격 정리
            price_clean = re.sub(r'[^0-9]', '', price_text)
            if price_clean and price_clean != '0':
                formatted_price = f"{int(price_clean):,}원"
            else:
                formatted_price = "품절"
            
            # 사양 정보 추출
            specifications = []
            
            # 1. 제품명에서 주요 사양 추출
            name_specs = self._extract_specs_from_name(product_name)
            if name_specs:
                specifications.extend(name_specs)
            
            # 2. .prd_subTxt에서 상세 사양 정보 추출
            prd_subTxt = item.select_one(".prd_subTxt")
            if prd_subTxt:
                spec_text = prd_subTxt.get_text(strip=True)
                if spec_text and len(spec_text) > 10:
                    clean_spec = re.sub(r'\s+', ' ', spec_text)
                    specifications.append(clean_spec[:200])
            
            # 기본값 설정
            if not specifications:
                specifications.append("컴퓨존 상품")
            
            # 최종 사양 스마트 중복 제거
            final_specs_text = " / ".join(specifications)
            deduplicated_specs = self._smart_deduplicate_specs(final_specs_text)
            
            return Product(
                name=product_name, 
                price=formatted_price, 
                specifications=deduplicated_specs,
                site="컴퓨존"
            )
            
        except Exception as e:
            return None

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

    def _extract_manufacturer(self, product_name: str) -> Optional[str]:
        """제품명에서 제조사 추출"""
        if not product_name:
            return None
        
        # [브랜드명] 형식 우선 추출
        bracket_match = re.search(r'\[([^\]]+)\]', product_name)
        if bracket_match:
            return bracket_match.group(1).strip()
        
        # 대괄호가 없으면 첫 단어 추출
        text = re.sub(r"\s+", " ", product_name).strip()
        words = text.split()
        
        if not words:
            return None
            
        # 건너뛸 단어들
        skip = {"신제품", "신상품", "공식인증", "병행수입", "벌크", "정품", "할인", "특가"}
        
        i = 0
        while i < len(words):
            word = words[i]
            if word not in skip and not any(skip_word in word for skip_word in skip):
                break
            i += 1
            
        if i >= len(words):
            return None
            
        return words[i]

    def _normalize_brand(self, text: str) -> str:
        """브랜드명 정규화"""
        t = (text or "").lower()
        t = re.sub(r"[\s._/-]+", " ", t).strip()
        aliases = {
            "wd": "western digital",
            "웨스턴 디지털": "western digital",
            "에이수스": "asus",
            "기가바이트": "gigabyte",
            "삼성": "삼성전자",
            "samsung": "삼성전자",
            "삼성전자": "삼성전자",
            "gigabyte": "gigabyte",
            "지스킬": "g skill",
            "gskill": "g skill"
        }
        return aliases.get(t, t)

    def _filter_by_maker(self, product: Product, maker_codes: List[str]) -> bool:
        """제조사 코드로 제품 필터링"""
        if not maker_codes:
            return True
        manufacturer = self._extract_manufacturer(product.name)
        if not manufacturer:
            return False
        man_norm = self._normalize_brand(manufacturer)
        
        # 브랜드 코드들을 정규화하여 비교
        for code in maker_codes:
            code_norm = self._normalize_brand(code.replace("_", " "))
            if man_norm == code_norm or man_norm in code_norm or code_norm in man_norm:
                return True
                
        # ID 매핑도 확인
        known_ids = {
            '2': '삼성전자', '14': 'gigabyte', '9': 'asus', '475': 'msi',
            '3400': 'adata', '18': 'kingston', '24': 'western digital'
        }
        for code in maker_codes:
            if code in known_ids:
                brand_name = known_ids[code]
                if man_norm == self._normalize_brand(brand_name):
                    return True
                    
        return False

    def get_unique_products(self, keyword: str, maker_codes: List[str]) -> List[Product]:
        """컴퓨존 고유 제품 검색"""
        products = self.search_products(keyword, "sale_order", maker_codes, limit=20)
        # 제조사 필터링 적용
        filtered_products = []
        for product in products:
            if self._filter_by_maker(product, maker_codes):
                filtered_products.append(product)
        return filtered_products[:10]

# ============================================================================
# 가이드컴 파서 (간소화된 버전)
# ============================================================================

class GuidecomParser:
    def __init__(self):
        self.base_url = "https://www.guidecom.co.kr/search/index.html"
        self.list_url = "https://www.guidecom.co.kr/search/list.php"
        self.session = requests.Session()
        self._setup_session()

    def _setup_session(self):
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
        ]
        
        self.session.headers.update({
            "User-Agent": random.choice(user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        })

    def get_search_options(self, keyword: str) -> List[Dict[str, str]]:
        """가이드컴 제조사 옵션 추출"""
        try:
            products = self.search_products(keyword, "reco_goods", [], limit=30)
            
            manufacturers = set()
            for product in products:
                manufacturer = self._extract_manufacturer(product.name)
                if manufacturer and len(manufacturer) > 1:
                    manufacturers.add(manufacturer)
            
            result = []
            for manufacturer in sorted(manufacturers):
                normalized = self._normalize_brand(manufacturer).replace(" ", "_")
                result.append({'name': manufacturer, 'code': normalized})
            
            return result[:10]  # 최대 10개
            
        except Exception as e:
            print(f"가이드컴 옵션 추출 실패: {e}")
            return []

    def _extract_manufacturer(self, product_name: str) -> Optional[str]:
        """제품명에서 제조사 추출"""
        if not product_name:
            return None
        
        # 대괄호 제거 및 정리
        text = re.sub(r"\[[^\]]+\]", " ", product_name)
        text = re.sub(r"\s+", " ", text).strip()
        words = text.split()
        
        if not words:
            return None
            
        # 건너뛸 단어들
        skip = {"신제품", "신상품", "공식인증", "병행수입", "벌크", "정품", "할인", "특가"}
        
        i = 0
        while i < len(words):
            word = words[i]
            if word not in skip and not any(skip_word in word for skip_word in skip):
                break
            i += 1
            
        if i >= len(words):
            return None
            
        manufacturer = words[i]
        
        # 2단어 브랜드 결합
        if i + 1 < len(words):
            pair = f"{manufacturer} {words[i+1]}"
            normalized_pair = self._normalize_brand(pair)
            if normalized_pair in {"western digital", "tp link", "g skill"}:
                manufacturer = pair
                
        return manufacturer

    def _normalize_brand(self, text: str) -> str:
        """브랜드명 정규화"""
        t = (text or "").lower()
        t = re.sub(r"[\s._/-]+", " ", t).strip()
        aliases = {
            "wd": "western digital",
            "웨스턴 디지털": "western digital",
            "에이수스": "asus",
            "기가바이트": "gigabyte",
            "삼성": "삼성전자",
            "samsung": "삼성전자",
        }
        return aliases.get(t, t)

    def _filter_by_maker(self, product: Product, maker_codes: List[str]) -> bool:
        """제조사 코드로 제품 필터링"""
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
        return False

    def search_products(self, keyword: str, sort_type: str, maker_codes: List[str], limit: int = 5) -> List[Product]:
        """가이드컴 제품 검색"""
        try:
            from urllib.parse import quote_plus
            
            # POST 데이터 준비
            data = {
                "keyword": keyword,
                "order": sort_type or "reco_goods",
                "lpp": min(limit * 2, 30),
                "page": 1,
                "y": 0
            }
            
            # 컴퓨터 부품 카테고리 추가 (SSD 관련)
            keyword_lower = keyword.lower()
            if any(k in keyword_lower for k in ["ssd", "하드", "디스크"]):
                data["cid"] = "8855"  # SSD 카테고리
            elif any(k in keyword_lower for k in ["그래픽", "gpu", "rtx", "gtx"]):
                data["cid"] = "8803"  # 그래픽카드 카테고리
            elif any(k in keyword_lower for k in ["메모리", "ram", "ddr"]):
                data["cid"] = "8802"  # 메모리 카테고리
            
            referer = f"https://www.guidecom.co.kr/search/?keyword={quote_plus(keyword)}"
            headers = {"Referer": referer}
            
            resp = self.session.post(self.list_url, data=data, headers=headers, timeout=30)
            resp.encoding = resp.apparent_encoding or 'euc-kr'
            
            if resp.status_code != 200:
                return []
                
            soup = BeautifulSoup(resp.text, "lxml")
            rows = soup.find_all("div", class_="goods-row")
            
            products = []
            for row in rows[:limit]:
                product = self._parse_guidecom_product(row, maker_codes)
                if product:
                    products.append(product)
                    
            return products
            
        except Exception as e:
            print(f"가이드컴 검색 실패: {e}")
            return []

    def _parse_guidecom_product(self, row, maker_codes: List[str]) -> Optional[Product]:
        """가이드컴 제품 파싱"""
        try:
            # 제품명 추출
            name_selectors = [
                ".desc .goodsname1",
                ".desc h4.title a",
                "h4.title a",
                ".desc .title a",
                ".title a"
            ]
            
            name = ""
            for selector in name_selectors:
                name_el = row.select_one(selector)
                if name_el:
                    name = name_el.get_text(strip=True)
                    break
                    
            if not name:
                return None
            
            # 제조사 필터링
            if maker_codes:
                manufacturer = self._extract_manufacturer(name)
                if not manufacturer:
                    return None
                    
                man_norm = self._normalize_brand(manufacturer)
                sel_norms = [self._normalize_brand(code.replace("_", " ")) for code in maker_codes]
                
                if not any(man_norm == sel or man_norm in sel or sel in man_norm for sel in sel_norms):
                    return None
            
            # 가격 추출
            price_selectors = [
                ".prices .price-large span",
                ".price-large span",
                ".price-large",
                ".prices .price span",
                ".price span",
                ".price"
            ]
            
            price = "품절"
            for selector in price_selectors:
                price_el = row.select_one(selector)
                if price_el:
                    price_text = price_el.get_text(strip=True)
                    digits = re.sub(r"[^0-9]", "", price_text)
                    if digits and digits != '0':
                        price = f"{int(digits):,}원"
                        break
            
            # 사양 추출
            spec_selectors = [
                ".desc .feature",
                ".feature",
                ".desc .spec",
                ".spec",
                ".desc .description"
            ]
            
            specs = "가이드컴 상품"
            for selector in spec_selectors:
                spec_el = row.select_one(selector)
                if spec_el:
                    specs = spec_el.get_text(strip=True)
                    if specs and specs != name:
                        break
            
            return Product(
                name=name,
                price=price,
                specifications=specs[:100] + "..." if len(specs) > 100 else specs,
                site="가이드컴"
            )
            
        except Exception:
            return None

    def get_unique_products(self, keyword: str, maker_codes: List[str]) -> List[Product]:
        """가이드컴 고유 제품 검색"""
        products = self.search_products(keyword, "reco_goods", maker_codes, limit=20)
        # 제조사 필터링 적용
        filtered_products = []
        for product in products:
            if self._filter_by_maker(product, maker_codes):
                filtered_products.append(product)
        return filtered_products[:10]

# ============================================================================
# 통합 검색 및 제품 그룹핑 클래스
# ============================================================================

class IntegratedSearcher:
    def __init__(self):
        self.danawa = DanawaParser()
        self.compuzone = CompuzoneParser()
        self.guidecom = GuidecomParser()
    
    def search_all_sites(self, keyword: str, maker_codes: List[str] = None) -> List[Product]:
        """모든 사이트에서 제품 검색"""
        all_products = []
        
        if maker_codes is None:
            maker_codes = []
        
        try:
            # 다나와 검색
            danawa_products = self.danawa.get_unique_products(keyword, maker_codes)
            all_products.extend(danawa_products)
            print(f"다나와: {len(danawa_products)}개 제품")
        except Exception as e:
            print(f"다나와 검색 실패: {e}")
        
        try:
            # 컴퓨존 검색
            compuzone_products = self.compuzone.get_unique_products(keyword, maker_codes)
            all_products.extend(compuzone_products)
            print(f"컴퓨존: {len(compuzone_products)}개 제품")
        except Exception as e:
            print(f"컴퓨존 검색 실패: {e}")
        
        try:
            # 가이드컴 검색
            guidecom_products = self.guidecom.get_unique_products(keyword, maker_codes)
            all_products.extend(guidecom_products)
            print(f"가이드컴: {len(guidecom_products)}개 제품")
        except Exception as e:
            print(f"가이드컴 검색 실패: {e}")
        
        return all_products
    
    def group_similar_products(self, products: List[Product], similarity_threshold: float = 0.6) -> List[ProductGroup]:
        """비슷한 제품들을 그룹핑"""
        if not products:
            return []
        
        groups = []
        ungrouped = products.copy()
        
        while ungrouped:
            # 첫 번째 제품을 기준으로 그룹 생성
            base_product = ungrouped.pop(0)
            group = ProductGroup(
                representative_name=self._clean_product_name(base_product.name),
                products=[base_product]
            )
            
            # 비슷한 제품들 찾기
            remaining = []
            for product in ungrouped:
                similarity = self._calculate_similarity(base_product.name, product.name)
                if similarity >= similarity_threshold:
                    group.products.append(product)
                else:
                    remaining.append(product)
            
            ungrouped = remaining
            groups.append(group)
        
        return groups
    
    def _clean_product_name(self, name: str) -> str:
        """제품명 정리 (브랜드 괄호, 특수문자 등 제거)"""
        # [브랜드] 제거
        cleaned = re.sub(r'\[[^\]]+\]', '', name)
        # 과도한 공백 정리
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        # 너무 길면 자르기
        if len(cleaned) > 50:
            cleaned = cleaned[:50] + "..."
        return cleaned
    
    def _calculate_similarity(self, name1: str, name2: str) -> float:
        """두 제품명의 유사도 계산"""
        # 간단한 전처리
        def normalize(text):
            # [브랜드] 제거
            text = re.sub(r'\[[^\]]+\]', '', text)
            # 특수문자 제거
            text = re.sub(r'[^\w\s]', ' ', text)
            # 공백 정리
            text = re.sub(r'\s+', ' ', text).strip().lower()
            return text
        
        norm1 = normalize(name1)
        norm2 = normalize(name2)
        
        # SequenceMatcher로 유사도 계산
        return SequenceMatcher(None, norm1, norm2).ratio()
    
    def get_all_brands(self, keyword: str) -> List[Dict[str, str]]:
        """모든 사이트에서 브랜드 옵션 수집"""
        all_brands = {}
        
        try:
            danawa_brands = self.danawa.get_search_options(keyword)
            for brand in danawa_brands:
                all_brands[brand['name']] = brand['code']
        except:
            pass
        
        try:
            compuzone_brands = self.compuzone.get_search_options(keyword)
            for brand in compuzone_brands:
                all_brands[brand['name']] = brand['code']
        except:
            pass
        
        try:
            guidecom_brands = self.guidecom.get_search_options(keyword)
            for brand in guidecom_brands:
                all_brands[brand['name']] = brand['code']
        except:
            pass
        
        # 중복 제거하고 정렬
        unique_brands = []
        for name, code in sorted(all_brands.items()):
            unique_brands.append({'name': name, 'code': code})
        
        return unique_brands[:15]  # 최대 15개