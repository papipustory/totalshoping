# -*- coding: utf-8 -*-
"""
통합 쇼핑몰 가격 비교 앱
- 다나와, 컴퓨존, 가이드컴 통합 검색
- 제품별 가격 비교표
- 엑셀 다운로드 기능
"""

import streamlit as st
import pandas as pd
from total import IntegratedSearcher, ProductGroup
import io
from datetime import datetime

# 페이지 설정
st.set_page_config(
    page_title="통합 쇼핑몰 가격 비교", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS 스타일 (기존 UI 유지)
st.markdown("""
<style>
    .main-header {
        text-align: center;
        padding: 1rem 0;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 10px;
        margin-bottom: 2rem;
    }
    .price-comparison-table {
        border-radius: 10px;
        overflow: hidden;
        margin: 1rem 0;
    }
    .site-danawa { background-color: #E3F2FD; }
    .site-compuzone { background-color: #F3E5F5; }
    .site-guidecom { background-color: #E8F5E8; }
</style>
""", unsafe_allow_html=True)

# 메인 헤더
st.markdown("""
<div class="main-header">
    <h1>🛒 통합 쇼핑몰 가격 비교</h1>
    <p>다나와 • 컴퓨존 • 가이드컴</p>
</div>
""", unsafe_allow_html=True)

# 세션 상태 초기화
if 'searcher' not in st.session_state:
    st.session_state.searcher = IntegratedSearcher()
if 'keyword' not in st.session_state:
    st.session_state.keyword = ""
if 'brands' not in st.session_state:
    st.session_state.brands = []
if 'selected_brands' not in st.session_state:
    st.session_state.selected_brands = {}
if 'search_results' not in st.session_state:
    st.session_state.search_results = []
if 'grouped_results' not in st.session_state:
    st.session_state.grouped_results = []

# 사이드바 - 검색 옵션
with st.sidebar:
    st.header("🔍 검색 설정")
    
    # 키워드 입력
    with st.form(key="search_form"):
        keyword_input = st.text_input(
            "검색어를 입력하세요:", 
            placeholder="예: RTX 5080, SSD 2TB",
            value=st.session_state.get("keyword", "")
        )
        search_button = st.form_submit_button("🔍 브랜드 검색", use_container_width=True)

    if search_button and keyword_input:
        st.session_state.keyword = keyword_input
        st.session_state.search_results = []
        st.session_state.grouped_results = []
        
        with st.spinner("브랜드 정보를 가져오는 중..."):
            try:
                brands = st.session_state.searcher.get_all_brands(keyword_input)
                st.session_state.brands = brands
                st.session_state.selected_brands = {brand['name']: False for brand in brands}
                
                if brands:
                    st.success(f"✅ {len(brands)}개 브랜드 발견!")
                else:
                    st.warning("⚠️ 브랜드를 찾을 수 없습니다.")
            except Exception as e:
                st.error(f"❌ 브랜드 검색 오류: {e}")

    # 브랜드 선택
    if st.session_state.brands:
        st.subheader("🏷️ 브랜드 선택")
        
        with st.form(key="brand_form"):
            # 전체 선택/해제
            col1, col2 = st.columns(2)
            with col1:
                select_all = st.button("전체 선택", use_container_width=True)
            with col2:
                select_none = st.button("전체 해제", use_container_width=True)
            
            if select_all:
                for brand in st.session_state.brands:
                    st.session_state.selected_brands[brand['name']] = True
                    
            if select_none:
                for brand in st.session_state.brands:
                    st.session_state.selected_brands[brand['name']] = False
            
            # 브랜드 체크박스
            for i, brand in enumerate(st.session_state.brands):
                st.checkbox(
                    f"{brand['name']}", 
                    key=f"brand_{i}",
                    value=st.session_state.selected_brands.get(brand['name'], False)
                )
            
            # 제품 검색 버튼
            product_search_button = st.form_submit_button("🛒 제품 검색", use_container_width=True)

        if product_search_button:
            # 선택된 브랜드 확인
            selected_codes = []
            for i, brand in enumerate(st.session_state.brands):
                if st.session_state[f"brand_{i}"]:
                    selected_codes.append(brand['code'])
            
            if not selected_codes:
                st.warning("⚠️ 하나 이상의 브랜드를 선택해주세요.")
            else:
                with st.spinner("모든 사이트에서 제품을 검색 중..."):
                    try:
                        # 통합 검색 실행
                        all_products = st.session_state.searcher.search_all_sites(
                            st.session_state.keyword, 
                            selected_codes
                        )
                        
                        if all_products:
                            # 제품 그룹핑
                            grouped = st.session_state.searcher.group_similar_products(
                                all_products, 
                                similarity_threshold=0.5
                            )
                            
                            st.session_state.search_results = all_products
                            st.session_state.grouped_results = grouped
                            
                            st.success(f"✅ 총 {len(all_products)}개 제품 발견!")
                            st.info(f"📊 {len(grouped)}개 제품군으로 그룹핑됨")
                        else:
                            st.warning("⚠️ 검색된 제품이 없습니다.")
                            
                    except Exception as e:
                        st.error(f"❌ 제품 검색 오류: {e}")

# 메인 화면 - 검색 결과 표시
if st.session_state.grouped_results:
    st.header(f"🎯 '{st.session_state.keyword}' 검색 결과")
    
    # 통계 정보
    col1, col2, col3, col4 = st.columns(4)
    
    total_products = len(st.session_state.search_results)
    danawa_count = len([p for p in st.session_state.search_results if p.site == "다나와"])
    compuzone_count = len([p for p in st.session_state.search_results if p.site == "컴퓨존"])
    guidecom_count = len([p for p in st.session_state.search_results if p.site == "가이드컴"])
    
    with col1:
        st.metric("전체 제품", total_products)
    with col2:
        st.metric("다나와", danawa_count)
    with col3:
        st.metric("컴퓨존", compuzone_count)
    with col4:
        st.metric("가이드컴", guidecom_count)
    
    # 탭으로 표시 방식 구분
    tab1, tab2 = st.tabs(["📊 가격 비교표", "📝 전체 목록"])
    
    with tab1:
        st.subheader("💰 제품별 가격 비교")
        
        # 가격 비교표 데이터 준비
        comparison_data = []
        
        for group in st.session_state.grouped_results:
            # 각 사이트별로 제품 정리
            sites_data = {"다나와": None, "컴퓨존": None, "가이드컴": None}
            
            for product in group.products:
                sites_data[product.site] = product
            
            # 가격 비교 행 생성
            for site, product in sites_data.items():
                if product:
                    comparison_data.append({
                        "제품명": group.representative_name if site == "다나와" else "",
                        "사이트": site,
                        "가격": product.price,
                        "세부사양": product.specifications[:100] + ("..." if len(product.specifications) > 100 else "")
                    })
                else:
                    comparison_data.append({
                        "제품명": group.representative_name if site == "다나와" else "",
                        "사이트": site,
                        "가격": "검색 안됨",
                        "세부사양": "-"
                    })
        
        if comparison_data:
            # 데이터프레임 생성
            df_comparison = pd.DataFrame(comparison_data)
            
            # 스타일링된 테이블 표시
            def highlight_site(row):
                if row['사이트'] == '다나와':
                    return ['background-color: #E3F2FD'] * len(row)
                elif row['사이트'] == '컴퓨존':
                    return ['background-color: #F3E5F5'] * len(row)
                elif row['사이트'] == '가이드컴':
                    return ['background-color: #E8F5E8'] * len(row)
                else:
                    return [''] * len(row)
            
            styled_df = df_comparison.style.apply(highlight_site, axis=1)
            st.dataframe(styled_df, use_container_width=True, height=600)
            
            # 엑셀 다운로드 버튼
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                df_comparison.to_excel(
                    writer, 
                    sheet_name='가격비교결과', 
                    index=False
                )
                
                # 요약 시트 추가
                summary_data = {
                    '검색어': [st.session_state.keyword],
                    '검색일시': [datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
                    '전체제품수': [total_products],
                    '다나와제품수': [danawa_count],
                    '컴퓨존제품수': [compuzone_count],
                    '가이드컴제품수': [guidecom_count]
                }
                pd.DataFrame(summary_data).to_excel(
                    writer, 
                    sheet_name='검색요약', 
                    index=False
                )
            
            excel_data = excel_buffer.getvalue()
            
            st.download_button(
                label="📥 엑셀로 다운로드",
                data=excel_data,
                file_name=f"가격비교_{st.session_state.keyword}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
    
    with tab2:
        st.subheader("📋 전체 제품 목록")
        
        # 전체 제품 목록 데이터프레임
        all_data = []
        for product in st.session_state.search_results:
            all_data.append({
                "사이트": product.site,
                "제품명": product.name,
                "가격": product.price,
                "세부사양": product.specifications
            })
        
        if all_data:
            df_all = pd.DataFrame(all_data)
            
            # 사이트별 필터
            site_filter = st.multiselect(
                "사이트 필터:",
                options=["다나와", "컴퓨존", "가이드컴"],
                default=["다나와", "컴퓨존", "가이드컴"]
            )
            
            if site_filter:
                df_filtered = df_all[df_all['사이트'].isin(site_filter)]
                st.dataframe(df_filtered, use_container_width=True, height=600)
            else:
                st.warning("⚠️ 최소 하나의 사이트를 선택해주세요.")

else:
    # 검색 결과가 없을 때 안내
    st.info("""
    👈 **사이드바에서 검색을 시작하세요!**
    
    1️⃣ **검색어 입력** - 원하는 제품명을 입력하세요
    2️⃣ **브랜드 선택** - 관심있는 브랜드를 선택하세요  
    3️⃣ **제품 검색** - 모든 사이트에서 검색합니다
    4️⃣ **가격 비교** - 사이트별 가격을 비교해보세요
    
    **💡 추천 검색어:** RTX 5080, SSD 2TB, RAM 32GB, 메인보드 B650
    """)

# 푸터
st.markdown("""
---
<div style="text-align: center; color: #666; margin-top: 2rem;">
    <p>🔄 실시간 가격 비교 • 📊 스마트 제품 그룹핑 • 📥 엑셀 다운로드</p>
    <p><small>Made with Streamlit • 다나와 & 컴퓨존 & 가이드컴</small></p>
</div>
""", unsafe_allow_html=True)