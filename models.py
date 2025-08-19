"""
=== 통합 상품 검색기 - 공통 데이터 모델 ===

이 모듈은 컴퓨존과 가이드컴에서 가져온 상품 정보를 
표준화된 형태로 저장하고 관리하기 위한 데이터 모델을 정의합니다.

주요 기능:
- 서로 다른 사이트의 상품 정보를 통일된 형태로 저장
- 데이터 검증 및 타입 힌트 제공
- Streamlit UI에서 쉽게 사용할 수 있는 표준 인터페이스

작성자: Claude AI
최종 수정일: 2025-01-19
"""

from dataclasses import dataclass
from typing import Optional
import re


@dataclass
class Product:
    """
    상품 정보를 저장하는 표준 데이터 클래스
    
    컴퓨존과 가이드컴에서 파싱한 상품 정보를 통일된 형태로 저장합니다.
    모든 필드는 문자열로 저장되어 UI에서 바로 표시할 수 있습니다.
    
    Attributes:
        name (str): 상품명 - 브랜드, 모델명, 주요 스펙 포함
                   예: "[삼성전자] 990 EVO 1TB M.2 NVMe SSD"
        
        price (str): 가격 정보 - 원화 표시 또는 상태 정보
                    예: "89,900원", "품절", "가격 문의"
        
        specifications (str): 주요 사양 정보 - "/"로 구분된 스펙 목록
                             예: "1TB / M.2 2280 / PCIe 4.0 / TLC"
        
        product_link (str): 상품 상세 페이지 링크 (선택사항)
                           예: "https://www.compuzone.co.kr/product/..."
        
        site (str): 출처 사이트 정보 (선택사항)
                   값: "컴퓨존", "가이드컴"
    
    사용 예시:
        >>> product = Product(
        ...     name="[삼성전자] 990 EVO 1TB",
        ...     price="89,900원", 
        ...     specifications="1TB / M.2 / PCIe 4.0",
        ...     site="컴퓨존"
        ... )
        >>> print(f"{product.site}: {product.name} - {product.price}")
    """
    
    # 필수 필드
    name: str                           # 상품명 (반드시 필요)
    price: str                          # 가격 정보 (반드시 필요)  
    specifications: str                 # 사양 정보 (반드시 필요)
    
    # 선택 필드 (기본값 제공)
    product_link: str = ""              # 상품 링크 (없을 수 있음)
    site: str = ""                      # 출처 사이트 (없을 수 있음)
    
    def __post_init__(self):
        """
        객체 생성 후 자동 호출되는 데이터 검증 및 정리 메서드
        
        수행하는 작업:
        1. 필수 필드 유효성 검사
        2. 문자열 정리 (공백 제거, None 처리)
        3. 가격 형식 표준화
        4. 사양 정보 정리
        """
        # 1. 필수 필드 검증
        if not self.name or not self.name.strip():
            raise ValueError("상품명은 비어있을 수 없습니다")
        
        if not self.price or not self.price.strip():
            raise ValueError("가격 정보는 비어있을 수 없습니다")
        
        # 2. 문자열 정리
        self.name = self._clean_string(self.name)
        self.price = self._clean_string(self.price)
        self.specifications = self._clean_string(self.specifications)
        self.product_link = self._clean_string(self.product_link)
        self.site = self._clean_string(self.site)
        
        # 3. 가격 정보 표준화
        self.price = self._standardize_price(self.price)
        
        # 4. 사양 정보 정리
        self.specifications = self._clean_specifications(self.specifications)
    
    def _clean_string(self, value: str) -> str:
        """
        문자열 정리 유틸리티 메서드
        
        Args:
            value: 정리할 문자열
            
        Returns:
            str: 정리된 문자열
        """
        if not value:
            return ""
        
        # 앞뒤 공백 제거 및 연속 공백을 단일 공백으로 변환
        cleaned = re.sub(r'\s+', ' ', str(value).strip())
        return cleaned
    
    def _standardize_price(self, price: str) -> str:
        """
        가격 정보를 표준 형식으로 변환
        
        Args:
            price: 원본 가격 문자열
            
        Returns:
            str: 표준화된 가격 문자열
        """
        if not price:
            return "가격 정보 없음"
        
        price_lower = price.lower()
        
        # 특수 상태 처리
        if any(word in price_lower for word in ['품절', '재고없음', '일시품절']):
            return "품절"
        
        if any(word in price_lower for word in ['문의', '전화', '상담']):
            return "가격 문의"
        
        # 숫자가 포함된 가격 표준화
        if re.search(r'\d', price):
            # 이미 "원"으로 끝나면 그대로 반환
            if price.endswith('원'):
                return price
            
            # 숫자만 추출해서 원화 형식으로 변환
            numbers = re.findall(r'\d+', price)
            if numbers:
                try:
                    price_num = int(''.join(numbers))
                    return f"{price_num:,}원"
                except ValueError:
                    pass
        
        return price
    
    def _clean_specifications(self, specs: str) -> str:
        """
        사양 정보를 정리하고 표준화
        
        Args:
            specs: 원본 사양 문자열
            
        Returns:
            str: 정리된 사양 문자열
        """
        if not specs:
            return "사양 정보 없음"
        
        # 슬래시로 구분된 사양들을 개별 정리
        spec_parts = [part.strip() for part in specs.split('/') if part.strip()]
        
        # 빈 사양이면 기본값 반환
        if not spec_parts:
            return "사양 정보 없음"
        
        # 중복 제거 (순서 유지)
        unique_specs = []
        seen = set()
        
        for spec in spec_parts:
            spec_clean = spec.lower().strip()
            if spec_clean not in seen and len(spec_clean) > 0:
                unique_specs.append(spec)
                seen.add(spec_clean)
        
        return " / ".join(unique_specs) if unique_specs else "사양 정보 없음"
    
    def get_display_price(self) -> str:
        """
        UI 표시용 가격 문자열 반환
        
        Returns:
            str: 표시용 가격 (이미 표준화된 형식)
        """
        return self.price
    
    def get_short_name(self, max_length: int = 50) -> str:
        """
        축약된 상품명 반환 (긴 상품명을 UI에 맞게 줄임)
        
        Args:
            max_length: 최대 문자 길이
            
        Returns:
            str: 축약된 상품명
        """
        if len(self.name) <= max_length:
            return self.name
        
        return self.name[:max_length-3] + "..."
    
    def is_price_available(self) -> bool:
        """
        가격이 실제 구매 가능한 상태인지 확인
        
        Returns:
            bool: 구매 가능한 가격이면 True
        """
        unavailable_terms = ['품절', '가격 문의', '가격 정보 없음', '재고없음']
        return not any(term in self.price for term in unavailable_terms)
    
    def get_numeric_price(self) -> Optional[int]:
        """
        가격에서 숫자 값을 추출
        
        Returns:
            int: 가격의 숫자 값, 추출 불가능하면 None
        """
        if not self.is_price_available():
            return None
        
        # 숫자만 추출
        numbers = re.findall(r'\d+', self.price)
        if numbers:
            try:
                return int(''.join(numbers))
            except ValueError:
                pass
        
        return None
    
    def __str__(self) -> str:
        """문자열 표현 (디버깅용)"""
        return f"Product(name='{self.get_short_name()}', price='{self.price}', site='{self.site}')"
    
    def __repr__(self) -> str:
        """개발자용 문자열 표현"""
        return (f"Product(name={self.name!r}, price={self.price!r}, "
                f"specifications={self.specifications!r}, site={self.site!r})")