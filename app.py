import streamlit as st
import pandas as pd
from compuzone import CompuzoneParser
from guidecom import GuidecomParser
import re
from concurrent.futures import ThreadPoolExecutor

st.set_page_config(page_title="통합 상품 검색", layout="wide")

st.title("🛒 통합 상품 검색기 (컴퓨존 + 가이드컴)")

# Initialize session state
if 'compuzone_parser' not in st.session_state:
    st.session_state.compuzone_parser = CompuzoneParser()
if 'guidecom_parser' not in st.session_state:
    st.session_state.guidecom_parser = GuidecomParser()
if 'keyword' not in st.session_state:
    st.session_state.keyword = ""
if 'manufacturers' not in st.session_state:
    st.session_state.manufacturers = []
if 'selected_manufacturers' not in st.session_state:
    st.session_state.selected_manufacturers = {}
if 'products' not in st.session_state:
    st.session_state.products = []

# --- 1. Keyword Input using a Form ---
with st.form(key="search_form"):
    keyword_input = st.text_input(
        "검색어를 입력하세요:", 
        placeholder="예: 그래픽카드, SSD"
    )
    search_button = st.form_submit_button(label="제조사 검색")

if search_button:
    st.session_state.keyword = keyword_input
    st.session_state.products = [] # 새로운 검색 시 이전 제품 결과 초기화
    if st.session_state.keyword:
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
                    st.warning("해당 검색어에 대한 제조사 정보를 찾을 수 없습니다.")
                else:
                    st.success(f"총 {len(st.session_state.manufacturers)}개 제조사를 찾았습니다.")
                    
            except Exception as e:
                st.error(f"제조사 검색 중 예상치 못한 오류가 발생했습니다: {str(e)}")
                st.session_state.manufacturers = []
    else:
        st.warning("검색어를 입력해주세요.")

# --- 2. Manufacturer Selection ---
if st.session_state.manufacturers:
    st.subheader("제조사를 선택하세요")
    
    # 전체 선택/해제 토글 버튼을 form 밖에 배치
    col1, col2 = st.columns([3, 1])
    with col2:
        # 현재 선택된 제조사 수 확인
        selected_count = 0
        for i in range(len(st.session_state.manufacturers)):
            if st.session_state.get(f"mfr_{i}", False):
                selected_count += 1
        
        # 모든 제조사가 선택되어 있으면 "전체 해제", 아니면 "전체 선택"
        if selected_count == len(st.session_state.manufacturers):
            button_text = "전체 해제"
        else:
            button_text = "전체 선택"
            
        if st.button(button_text):
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
        # 폼 제출 후, st.session_state에서 직접 각 체크박스의 상태를 읽어옵니다.
        selected_codes = []
        for i, manufacturer in enumerate(st.session_state.manufacturers):
            if st.session_state[f"mfr_{i}"]:
                # 각 제조사의 모든 사이트별 코드를 추가
                selected_codes.extend(manufacturer['codes'])
        
        if not selected_codes:
            st.warning("하나 이상의 제조사를 선택해주세요.")
        else:
            with st.spinner('제품 정보를 병렬로 검색 중입니다... (컴퓨존 + 가이드컴)'):
                try:
                    compuzone_products = []
                    guidecom_products = []

                    with ThreadPoolExecutor(max_workers=2) as executor:
                        future_compuzone = executor.submit(st.session_state.compuzone_parser.get_unique_products, st.session_state.keyword, selected_codes)
                        future_guidecom = executor.submit(st.session_state.guidecom_parser.get_unique_products, st.session_state.keyword, selected_codes)

                        try:
                            compuzone_products = future_compuzone.result() or []
                            st.success(f"컴퓨존에서 {len(compuzone_products)}개 제품 검색 완료")
                        except Exception as e:
                            st.warning(f"컴퓨존 제품 검색 중 오류: {str(e)}")

                        try:
                            guidecom_products = future_guidecom.result() or []
                            st.success(f"가이드컴에서 {len(guidecom_products)}개 제품 검색 완료")
                        except Exception as e:
                            st.warning(f"가이드컴 제품 검색 중 오류: {str(e)}")
                    
                    # 제품 통합
                    all_products = compuzone_products + guidecom_products
                    st.session_state.products = all_products
                    
                    if not st.session_state.products:
                        st.info("선택된 제조사의 제품을 찾을 수 없습니다.")
                    else:
                        st.success(f"총 {len(st.session_state.products)}개 제품을 찾았습니다!")
                        
                except Exception as e:
                    st.error(f"제품 검색 중 예상치 못한 오류가 발생했습니다: {str(e)}")
                    st.session_state.products = []
                    
                # 검색이 완료되면 페이지를 새로고침하여 결과를 즉시 표시합니다.
                st.rerun()
    

# --- 3. Display Results ---
if st.session_state.products:
    st.subheader(f"'{st.session_state.keyword}'에 대한 검색 결과")

    # 가격순으로 정렬하기 위한 헬퍼 함수
    def extract_price(product):
        try:
            # "원"과 ","를 제거하고 숫자로 변환
            price_str = product.price.replace('원', '').replace(',', '')
            return int(price_str)
        except (ValueError, AttributeError):
            # "가격 문의" 등 변환 불가능한 경우, 맨 뒤로 보내기 위해 무한대 값 반환
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
        for key in ['keyword', 'manufacturers', 'selected_manufacturers', 'products']:
            if key in st.session_state:
                if key == 'keyword':
                    st.session_state[key] = ""
                elif key in ['manufacturers', 'products']:
                    st.session_state[key] = []
                else:  # selected_manufacturers
                    st.session_state[key] = {}
        
        # 제조사 체크박스 상태도 초기화
        keys_to_remove = [k for k in st.session_state.keys() if k.startswith('mfr_')]
        for key in keys_to_remove:
            del st.session_state[key]
            
        st.rerun()
