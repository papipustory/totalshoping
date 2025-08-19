"""
=== 통합 상품 검색기 - Streamlit 메인 애플리케이션 ===

컴퓨존과 가이드컴을 통합하여 PC 부품 가격 비교 서비스를 제공하는 
Streamlit 웹 애플리케이션입니다.

주요 기능:
1. 통합 검색: 두 사이트에서 동시에 상품 검색
2. 제조사 필터링: 검색 결과에서 원하는 제조사만 선별
3. 가격 비교: 최저가 표시 및 정렬
4. 반응형 UI: 다크/라이트 모드 지원
5. 실시간 검색: 병렬 처리로 빠른 응답

사용 방법:
1. 검색어 입력 (예: "SSD", "RTX 4090", "DDR5 32GB")
2. "제조사 검색" 버튼 클릭
3. 원하는 제조사 선택
4. "선택한 제조사로 제품 검색" 버튼 클릭
5. 통합 결과 확인

기술 스택:
- Streamlit: 웹 UI 프레임워크
- BeautifulSoup: HTML 파싱
- ThreadPoolExecutor: 병렬 처리
- Pandas: 데이터 테이블 표시

작성자: Claude AI
최종 수정일: 2025-01-19
"""

import streamlit as st
import pandas as pd
from compuzone import CompuzoneParser
from guidecom import GuidecomParser
from models import Product
import re
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional
import time

# ========== Streamlit 페이지 설정 ==========
st.set_page_config(
    page_title="통합 상품 검색기",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ========== UI 개선을 위한 CSS ==========
st.markdown("""
<style>
/* 폼 제출 후 깜빡임 최소화 */
.stForm {
    border: 1px solid #e0e0e0;
    border-radius: 10px;
    padding: 1rem;
    margin-bottom: 1rem;
}

/* 검색 중일 때 부드러운 전환 효과 */
.stSpinner {
    background-color: rgba(255, 255, 255, 0.9);
}

/* 체크박스 그룹 정렬 개선 */
.stCheckbox {
    margin-bottom: 0.5rem;
}

/* 버튼 스타일 개선 */
.stButton > button {
    border-radius: 5px;
    border: 1px solid #ff4b4b;
    transition: all 0.3s ease;
}

.stButton > button:hover {
    transform: translateY(-1px);
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

/* 정보 메시지 스타일 */
.stInfo {
    border-radius: 8px;
    border-left: 4px solid #0073e6;
    animation: fadeIn 0.3s ease-in;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(-10px); }
    to { opacity: 1; transform: translateY(0); }
}
</style>
""", unsafe_allow_html=True)

# ========== 메인 타이틀 ==========
st.title("🛒 통합 상품 검색기")
st.markdown("### 컴퓨존 ➕ 가이드컴 통합 가격 비교")
st.markdown("---")

# ========== 세션 상태 초기화 ==========
def initialize_session_state():
    """
    Streamlit 세션 상태를 초기화합니다.
    
    페이지 새로고침 시에도 파서 인스턴스와 검색 상태가 유지되도록 
    st.session_state에 필요한 변수들을 설정합니다.
    
    초기화되는 변수들:
    - 파서 인스턴스: 컴퓨존, 가이드컴 파서 객체
    - 검색 관련: 키워드, 제조사 목록, 검색 상태
    - UI 상태: 선택된 제조사, 최종 상품 결과
    """
    
    # 파서 인스턴스 초기화 (한 번만 생성, 재사용)
    if 'compuzone_parser' not in st.session_state:
        with st.spinner("컴퓨존 파서 초기화 중..."):
            st.session_state.compuzone_parser = CompuzoneParser()
    
    if 'guidecom_parser' not in st.session_state:
        with st.spinner("가이드컴 파서 초기화 중..."):
            st.session_state.guidecom_parser = GuidecomParser()
    
    # 검색 상태 변수들 초기화
    session_defaults = {
        'keyword': "",                          # 현재 검색어
        'manufacturers': [],                    # 검색된 제조사 목록
        'selected_manufacturers': {},           # 사용자가 선택한 제조사
        'products': [],                         # 최종 검색 결과 상품들
        'searching_products': False,            # 제품 검색 진행 중 플래그
        'last_search_time': 0,                  # 마지막 검색 시간 (중복 방지)
    }
    
    for key, default_value in session_defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

# 세션 상태 초기화 실행
initialize_session_state()

# ========== 1단계: 검색어 입력 폼 ==========
def render_search_form():
    """
    검색어 입력 폼을 렌더링하고 검색 버튼 클릭을 처리합니다.
    
    Returns:
        tuple: (검색어, 검색 버튼 클릭 여부)
    """
    st.subheader("🔍 검색어 입력")
    
    with st.form(key="search_form"):
        # 검색어 입력 필드
        keyword_input = st.text_input(
            "검색할 상품명을 입력하세요:",
            placeholder="예: RTX 4090, SSD 1TB, DDR5 32GB, HDD 4TB",
            help="PC 부품명, 브랜드명, 용량 등을 입력하세요"
        )
        
        
        # 검색 버튼
        search_button = st.form_submit_button(
            label="🔎 제조사 검색 시작",
            help="입력한 검색어로 관련 제조사들을 찾습니다"
        )
    
    return keyword_input, search_button

# 검색 폼 렌더링
keyword_input, search_button = render_search_form()

# ========== 제조사 검색 처리 ==========
if search_button:
    st.session_state.keyword = keyword_input
    st.session_state.products = [] # 새로운 검색 시 이전 제품 결과 초기화
    st.session_state.manufacturers = [] # 이전 제조사 목록도 초기화
    st.session_state.selected_manufacturers = {}
    
    if st.session_state.keyword:
        # 동적 상태 메시지 컨테이너 생성
        status_container = st.empty()
        status_container.info("🔍 제조사 정보를 검색하고 있습니다...")
        
        with st.spinner("제조사 정보를 병렬로 가져오는 중... (컴퓨존 + 가이드컴)"):
            try:
                compuzone_mfrs = []
                guidecom_mfrs = []

                with ThreadPoolExecutor(max_workers=2) as executor:
                    future_compuzone = executor.submit(st.session_state.compuzone_parser.get_search_options, st.session_state.keyword)
                    future_guidecom = executor.submit(st.session_state.guidecom_parser.get_search_options, st.session_state.keyword)

                    try:
                        compuzone_mfrs = future_compuzone.result() or []
                    except Exception as e:
                        st.warning(f"컴퓨존 제조사 검색 중 오류: {str(e)}")

                    try:
                        guidecom_mfrs = future_guidecom.result() or []
                    except Exception as e:
                        st.warning(f"가이드컴 제조사 검색 중 오류: {str(e)}")
                
                # 제조사 통합 (각 사이트별 코드 보존)
                all_mfrs = {}
                for mfr in compuzone_mfrs + guidecom_mfrs:
                    if isinstance(mfr, dict) and 'name' in mfr:
                        mfr_key = mfr['name'].lower().strip()
                        if mfr_key not in all_mfrs:
                            # 첫 번째 제조사: 그대로 저장하되 codes 리스트로 변환
                            all_mfrs[mfr_key] = {
                                'name': mfr['name'],
                                'codes': [mfr['code']]  # 코드를 리스트로 저장
                            }
                        else:
                            # 같은 이름의 제조사: 코드만 추가
                            if mfr['code'] not in all_mfrs[mfr_key]['codes']:
                                all_mfrs[mfr_key]['codes'].append(mfr['code'])
                
                st.session_state.manufacturers = list(all_mfrs.values())
                st.session_state.selected_manufacturers = {m['name']: False for m in st.session_state.manufacturers}
                
                if not st.session_state.manufacturers:
                    status_container.warning("해당 검색어에 대한 제조사 정보를 찾을 수 없습니다.")
                else:
                    # 개별 사이트별 제조사 개수 계산
                    compuzone_count = len(compuzone_mfrs)
                    guidecom_count = len(guidecom_mfrs)
                    total_count = len(st.session_state.manufacturers)
                    
                    status_container.success(f"총 {total_count}개 제조사를 찾았습니다 (컴퓨존 {compuzone_count}개, 가이드컴 {guidecom_count}개)")
                    
            except Exception as e:
                status_container.error(f"제조사 검색 중 예상치 못한 오류가 발생했습니다: {str(e)}")
                st.session_state.manufacturers = []
    else:
        st.warning("검색어를 입력해주세요.")

# --- 2. Manufacturer Selection ---
if st.session_state.searching_products:
    # 제품 검색 중일 때만 표시
    st.info("🔍 선택한 제조사의 제품을 검색 중입니다...")
elif st.session_state.manufacturers:
    st.subheader("제조사를 선택하세요")
    
    # 현재 선택된 제조사 수 미리 계산 (폼 밖에서)
    selected_count = 0
    for i in range(len(st.session_state.manufacturers)):
        if st.session_state.get(f"mfr_{i}", False):
            selected_count += 1
    
    # 모든 제조사가 선택되어 있으면 "전체 해제", 아니면 "전체 선택"
    if selected_count == len(st.session_state.manufacturers):
        toggle_button_text = "전체 해제"
    else:
        toggle_button_text = "전체 선택"
    
    # 전체 선택/해제 버튼을 폼 밖에 배치 (오른쪽 정렬)
    col1, col2 = st.columns([3, 1])
    with col2:
        toggle_button = st.button(toggle_button_text, key="toggle_manufacturers")
    
    # 전체 선택/해제 버튼 처리
    if toggle_button:
        if selected_count == len(st.session_state.manufacturers):
            # 모든 체크박스를 False로 설정
            for i in range(len(st.session_state.manufacturers)):
                st.session_state[f"mfr_{i}"] = False
        else:
            # 모든 체크박스를 True로 설정
            for i in range(len(st.session_state.manufacturers)):
                st.session_state[f"mfr_{i}"] = True
        st.rerun()
    
    with st.form(key="manufacturer_form"):
        cols = st.columns(4)
        for i, manufacturer in enumerate(st.session_state.manufacturers):
            with cols[i % 4]:
                # 각 체크박스에 고유한 key를 할당합니다. Streamlit이 이 key를 사용해 상태를 관리합니다.
                st.checkbox(manufacturer['name'], key=f"mfr_{i}")
        
        # 제품 검색 버튼
        product_search_button = st.form_submit_button("선택한 제조사로 제품 검색")
    
    if product_search_button:
        # 제품 검색 시작 - 검색 중 상태 설정
        st.session_state.searching_products = True
        st.session_state.products = [] # 이전 제품 결과 초기화
        
        # 폼 제출 후, st.session_state에서 직접 각 체크박스의 상태를 읽어옵니다.
        selected_codes = []
        for i, manufacturer in enumerate(st.session_state.manufacturers):
            if st.session_state[f"mfr_{i}"]:
                # 각 제조사의 모든 사이트별 코드를 추가
                selected_codes.extend(manufacturer['codes'])
        
        if not selected_codes:
            st.session_state.searching_products = False
            st.warning("하나 이상의 제조사를 선택해주세요.")
        else:
            # 제품 검색용 동적 상태 메시지 컨테이너 생성
            product_status_container = st.empty()
            product_status_container.info("🛒 선택한 제조사의 제품을 검색하고 있습니다...")
            
            with st.spinner('제품 정보를 병렬로 검색 중입니다... (컴퓨존 + 가이드컴)'):
                try:
                    compuzone_products = []
                    guidecom_products = []

                    with ThreadPoolExecutor(max_workers=2) as executor:
                        future_compuzone = executor.submit(st.session_state.compuzone_parser.get_unique_products, st.session_state.keyword, selected_codes)
                        future_guidecom = executor.submit(st.session_state.guidecom_parser.get_unique_products, st.session_state.keyword, selected_codes)

                        try:
                            compuzone_products = future_compuzone.result() or []
                        except Exception as e:
                            st.warning(f"컴퓨존 제품 검색 중 오류: {str(e)}")

                        try:
                            guidecom_products = future_guidecom.result() or []
                        except Exception as e:
                            st.warning(f"가이드컴 제품 검색 중 오류: {str(e)}")
                    
                    # 제품 통합
                    all_products = compuzone_products + guidecom_products
                    st.session_state.products = all_products
                    
                    # 개별 사이트별 제품 개수 계산
                    compuzone_count = len(compuzone_products)
                    guidecom_count = len(guidecom_products)
                    total_count = len(st.session_state.products)
                    
                    if not st.session_state.products:
                        product_status_container.info("선택된 제조사의 제품을 찾을 수 없습니다.")
                    else:
                        product_status_container.success(f"'{st.session_state.keyword}' 검색 결과: 총 {total_count}개 제품 (컴퓨존 {compuzone_count}개, 가이드컴 {guidecom_count}개)")
                        
                except Exception as e:
                    product_status_container.error(f"제품 검색 중 예상치 못한 오류가 발생했습니다: {str(e)}")
                    st.session_state.products = []
                
                # 검색 완료 - 검색 중 상태 해제
                st.session_state.searching_products = False
                    
                # 검색이 완료되면 페이지를 새로고침하여 결과를 즉시 표시합니다.
                st.rerun()
    

# --- 3. Display Results ---
if st.session_state.products:
    st.subheader(f"'{st.session_state.keyword}'에 대한 검색 결과")

    # 가격순으로 정렬하기 위한 헬퍼 함수
    def extract_price(product):
        try:
            # 정규식으로 숫자만 추출 (더 효율적)
            price_digits = re.sub(r'[^\d]', '', product.price)
            return int(price_digits) if price_digits else float('inf')
        except (ValueError, AttributeError):
            # 변환 불가능한 경우, 맨 뒤로 정렬
            return float('inf')

    # 최저가 찾기 (가격이 숫자인 제품들만)
    valid_prices = []
    for product in st.session_state.products:
        price_num = extract_price(product)
        if price_num != float('inf'):
            valid_prices.append(price_num)
    
    min_price = min(valid_prices) if valid_prices else None
    
    # 제품 목록을 가격 오름차순으로 정렬
    sorted_products = sorted(st.session_state.products, key=extract_price)
    
    # 사이트별 카운터
    site_counters = {"컴퓨존": 0, "가이드컴": 0}
    
    # 데이터프레임 생성
    data = []
    for i, p in enumerate(sorted_products):
        # 사이트 정보 안전 처리
        site_name = getattr(p, 'site', '') or "컴퓨존"  # 기본값은 컴퓨존
        if site_name not in site_counters:
            site_counters[site_name] = 0
            
        # 사이트별 링크 번호
        site_counters[site_name] += 1
        site_link_num = site_counters[site_name]
        
        # 최저가 표시
        price_num = extract_price(p)
        is_lowest = min_price and price_num == min_price and price_num != float('inf')
        price_display = f"💰 {p.price}" if is_lowest else p.price
        
        # 구매링크 생성
        product_link = getattr(p, 'product_link', '') or ""
        if product_link:
            purchase_link = f'<a href="{product_link}" target="_blank">{site_name}{site_link_num}</a>'
        else:
            purchase_link = "링크없음"
        
        data.append({
            "No.": i + 1,
            "제품명": p.name,
            "가격": price_display,
            "주요 사양": p.specifications,
            "구매링크": purchase_link
        })
    
    df_with_links = pd.DataFrame(data)
    
    # 다크모드와 라이트모드 모두 지원하는 테이블 스타일
    st.markdown("""
    <style>
    .adaptive-table {
        width: 100%;
        border-collapse: collapse;
        font-family: "Source Sans Pro", sans-serif;
        font-size: 14px;
        background-color: var(--background-color);
        color: var(--text-primary-color);
    }
    
    /* 라이트 모드 기본값 */
    .adaptive-table {
        --background-color: white;
        --text-primary-color: rgb(38, 39, 48);
        --header-bg-color: rgb(240, 242, 246);
        --border-color: rgb(230, 234, 241);
        --hover-bg-color: rgb(245, 245, 245);
        --link-color: rgb(255, 75, 75);
    }
    
    /* 다크 모드 감지 및 적용 */
    @media (prefers-color-scheme: dark) {
        .adaptive-table {
            --background-color: rgb(14, 17, 23);
            --text-primary-color: rgb(250, 250, 250);
            --header-bg-color: rgb(38, 39, 48);
            --border-color: rgb(68, 70, 84);
            --hover-bg-color: rgb(38, 39, 48);
            --link-color: rgb(255, 115, 115);
        }
    }
    
    /* 스트림릿 다크 테마 클래스 감지 */
    [data-theme="dark"] .adaptive-table {
        --background-color: rgb(14, 17, 23);
        --text-primary-color: rgb(250, 250, 250);
        --header-bg-color: rgb(38, 39, 48);
        --border-color: rgb(68, 70, 84);
        --hover-bg-color: rgb(38, 39, 48);
        --link-color: rgb(255, 115, 115);
    }
    
    .adaptive-table th {
        background-color: var(--header-bg-color);
        color: var(--text-primary-color);
        font-weight: 600;
        padding: 0.5rem 0.75rem;
        text-align: left;
        border-bottom: 1px solid var(--border-color);
    }
    
    .adaptive-table td {
        padding: 0.5rem 0.75rem;
        border-bottom: 1px solid var(--border-color);
        color: var(--text-primary-color);
        background-color: var(--background-color);
    }
    
    .adaptive-table tr:hover td {
        background-color: var(--hover-bg-color);
    }
    
    .adaptive-table a {
        color: var(--link-color);
        text-decoration: none;
        font-weight: 600;
        padding: 2px 6px;
        border-radius: 3px;
        border: 1px solid var(--link-color);
        background-color: transparent;
        transition: all 0.2s ease;
    }
    
    .adaptive-table a:hover {
        background-color: var(--link-color);
        color: var(--background-color);
    }
    
    /* 열 너비 조정 */
    .adaptive-table th:nth-child(1), .adaptive-table td:nth-child(1) {
        width: 5%;  /* No. 열 */
    }
    
    .adaptive-table th:nth-child(2), .adaptive-table td:nth-child(2) {
        width: 35%; /* 제품명 열 */
    }
    
    .adaptive-table th:nth-child(3), .adaptive-table td:nth-child(3) {
        width: 12%; /* 가격 열 */
    }
    
    .adaptive-table th:nth-child(4), .adaptive-table td:nth-child(4) {
        width: 33%; /* 주요 사양 열 (기존보다 약간 줄임) */
    }
    
    .adaptive-table th:nth-child(5), .adaptive-table td:nth-child(5) {
        width: 15%; /* 구매링크 열 (기존보다 넓힘) */
        white-space: nowrap; /* 링크가 다음 줄로 넘어가지 않도록 */
        text-align: center; /* 중앙 정렬 */
    }
    </style>
    """, unsafe_allow_html=True)
    
    html_table = df_with_links.to_html(escape=False, index=False, classes='adaptive-table')
    st.markdown(html_table, unsafe_allow_html=True)

    # Reset button
    if st.button("새로 검색하기"):
        # 모든 상태 초기화
        for key in ['keyword', 'manufacturers', 'selected_manufacturers', 'products', 'searching_products']:
            if key in st.session_state:
                if key == 'keyword':
                    st.session_state[key] = ""
                elif key in ['manufacturers', 'products']:
                    st.session_state[key] = []
                elif key == 'searching_products':
                    st.session_state[key] = False
                else:  # selected_manufacturers
                    st.session_state[key] = {}
        
        # 제조사 체크박스 상태도 초기화
        keys_to_remove = [k for k in st.session_state.keys() if k.startswith('mfr_')]
        for key in keys_to_remove:
            del st.session_state[key]
            
        st.rerun()
