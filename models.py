"""
공통 데이터 모델 정의
"""

from dataclasses import dataclass

@dataclass
class Product:
    name: str
    price: str
    specifications: str
    product_link: str = ""
    site: str = ""  # "컴퓨존" 또는 "가이드컴"